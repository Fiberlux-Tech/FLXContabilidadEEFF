"""Headcount service — load, cache, CSV-parse, and persist employee roster data.

Headcount is computed via SQL COUNT(DISTINCT empleado) from the roster table.
"""

import csv
import io
import logging
import re

from config.calendar import MONTH_NAMES
from data.headcount_db import (
    fetch_headcount, bulk_upsert_roster, fetch_roster_detail,
    roster_count,
)
from data_service import LRUTTLCache

logger = logging.getLogger("flxcontabilidad.headcount_service")

_cache = LRUTTLCache("headcount", ttl=600, max_entries=40)

# Matches column headers like "2025-01", "2026-12"
_YEAR_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


def load_headcount(db_path: str, cia: str, year: int) -> dict:
    """Return headcount map keyed by CENTRO_COSTO with month-name values.

    Example return::

        {
            "100.101.00": {"JAN": 22, "FEB": 23, ..., "TOTAL_AVG": 22.5},
        }
    """
    cached = _cache.get(cia, year)
    if cached is not None:
        return cached

    rows = fetch_headcount(db_path, cia, year)
    result: dict[str, dict[str, float]] = {}
    for r in rows:
        ceco = r["centro_costo"]
        month_num = r["year_month"] % 100
        month_name = MONTH_NAMES.get(month_num)
        if month_name is None:
            continue
        if ceco not in result:
            result[ceco] = {}
        result[ceco][month_name] = r["headcount"]

    # Compute TOTAL_AVG for each CECO (average of months with data)
    for ceco, months in result.items():
        values = [v for k, v in months.items() if k != "TOTAL_AVG"]
        months["TOTAL_AVG"] = round(sum(values) / len(values), 2) if values else 0

    _cache.set(cia, year, result)
    return result


def load_headcount_ym(db_path: str, cia: str, years: list[int]) -> dict:
    """Return headcount map keyed by CENTRO_COSTO → year_month integer → count.

    Uses the database convention of year_month integers (e.g. 202501).

    Example return::

        {
            "100.101.00": {202501: 22, 202502: 23, ...},
        }
    """
    result: dict[str, dict[int, float]] = {}
    for year in years:
        cached = _cache.get(cia, year)
        if cached is not None:
            # Convert month-name cache back to year_month keys
            name_to_num = {v: k for k, v in MONTH_NAMES.items()}
            for ceco, months in cached.items():
                if ceco not in result:
                    result[ceco] = {}
                for key, val in months.items():
                    if key == "TOTAL_AVG":
                        continue
                    num = name_to_num.get(key)
                    if num is not None:
                        result[ceco][year * 100 + num] = val
            continue

        rows = fetch_headcount(db_path, cia, year)
        for r in rows:
            ceco = r["centro_costo"]
            if ceco not in result:
                result[ceco] = {}
            result[ceco][r["year_month"]] = r["headcount"]

    return result


def save_headcount_csv(db_path: str, cia: str | None, csv_content: str) -> int:
    """Parse an employee-roster CSV and store raw rows in the database.

    Expected CSV layout (one row per employee per month)::

        Año-Mes,EMPRESA,EMPLEADO,NOMBRE,CENTRO DE COSTO,COD CENTRO DE COSTO
        2025-01,FIBERLINE,44825996,PASACHE SAMAME ...,COMERCIAL II,200.101.02
        2025-01,ROP,74059735,ABURTO VICUÑA ...,LEGAL,300.101.03

    Processing:
    - Rows where EMPRESA = 'ROP' are skipped (not a valid company).
    - If ``cia`` is provided, only rows matching that EMPRESA are kept.
      If ``cia`` is None, all non-ROP companies are processed.

    Returns the number of roster rows saved.
    """
    reader = csv.reader(io.StringIO(csv_content))
    header = next(reader, None)
    if header is None:
        return 0

    col_map = _detect_roster_columns(header)
    nombre_idx = col_map.get("nombre")

    roster_rows: list[dict] = []
    companies: set[str] = set()

    for row in reader:
        if len(row) <= max(col_map.values()):
            continue

        empresa = row[col_map["empresa"]].strip().upper()
        if empresa == "ROP":
            continue
        if cia and empresa != cia:
            continue

        empleado = row[col_map["empleado"]].strip()
        ceco_code = row[col_map["ceco_code"]].strip()
        ano_mes = row[col_map["ano_mes"]].strip()
        nombre = row[nombre_idx].strip() if nombre_idx is not None else ""

        if not empleado or not ceco_code or not ano_mes:
            continue

        m = _YEAR_MONTH_RE.match(ano_mes)
        if not m:
            continue
        ym = int(m.group(1)) * 100 + int(m.group(2))

        roster_rows.append({
            "cia": empresa,
            "centro_costo": ceco_code,
            "year_month": ym,
            "empleado": empleado,
            "nombre": nombre,
        })
        companies.add(empresa)

    # Append new rows (duplicates ignored via UNIQUE constraint)
    saved = bulk_upsert_roster(db_path, roster_rows)

    # Invalidate cache for all affected companies
    years = {r["year_month"] // 100 for r in roster_rows}
    for emp in companies:
        for y in years:
            _cache.pop(emp, y)

    logger.info("CSV roster import: %d roster rows saved", saved)
    return saved


def get_roster_detail(
    db_path: str, cia: str, centro_costo: str, year_month: int,
) -> list[dict]:
    """Return individual employees for a specific company/CECO/month."""
    return fetch_roster_detail(db_path, cia, centro_costo, year_month)


def invalidate_headcount_cache(
    cia: str | None = None, year: int | None = None,
) -> None:
    """Manually invalidate headcount cache."""
    if cia and year:
        _cache.pop(cia, year)
    else:
        _cache.clear()


# ── helpers ──────────────────────────────────────────────────────────────

# Known header aliases → canonical key
_HEADER_ALIASES: dict[str, list[str]] = {
    "ano_mes": ["AÑO-MES", "ANO-MES", "AÑO_MES", "ANO_MES", "YEAR_MONTH", "MES"],
    "empresa": ["EMPRESA", "CIA", "COMPANY"],
    "empleado": ["EMPLEADO", "EMPLOYEE", "EMPLEADO_ID", "ID_EMPLEADO"],
    "nombre": ["NOMBRE", "NAME", "NOMBRE_EMPLEADO"],
    "ceco_code": [
        "COD_CENTRO_DE_COSTO", "COD_CENTRO_COSTO", "CECO_CODE",
    ],
}


def _detect_roster_columns(header: list[str]) -> dict[str, int]:
    """Map canonical column names to their index in the CSV header.

    Raises ValueError if any required column is not found.
    """
    normalised = [
        h.strip().upper().replace(" ", "_").replace("-", "_")
        for h in header
    ]
    result: dict[str, int] = {}
    for key, aliases in _HEADER_ALIASES.items():
        for i, col in enumerate(normalised):
            if col in [a.replace("-", "_") for a in aliases]:
                result[key] = i
                break
    # Fallback: assume standard column order if header detection fails
    missing = [k for k in _HEADER_ALIASES if k not in result]
    if missing:
        # Try positional fallback: A=año-mes, B=empresa, C=empleado, D=nombre, F=cod ceco
        if len(header) >= 6:
            result.setdefault("ano_mes", 0)
            result.setdefault("empresa", 1)
            result.setdefault("empleado", 2)
            result.setdefault("nombre", 3)
            result.setdefault("ceco_code", 5)
        else:
            raise ValueError(
                f"Could not detect required columns: {missing}. "
                f"Expected headers: Año-Mes, EMPRESA, EMPLEADO, COD CENTRO DE COSTO"
            )
    return result
