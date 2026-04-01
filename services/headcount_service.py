"""Headcount service — load, cache, CSV-parse, and persist headcount data."""

import csv
import io
import logging
import re

from config.calendar import MONTH_NAMES
from data.headcount_db import fetch_headcount, bulk_upsert, delete_headcount
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


def save_headcount(db_path: str, cia: str, records: list[dict]) -> int:
    """Upsert headcount records from JSON payload and invalidate cache."""
    tagged = [{"cia": cia, **r} for r in records]
    count = bulk_upsert(db_path, tagged)
    _invalidate_years(cia, tagged)
    return count


def save_headcount_csv(db_path: str, cia: str | None, csv_content: str) -> int:
    """Parse an employee-roster CSV, count distinct employees per CECO/month,
    and upsert the resulting headcount records.

    Expected CSV layout (one row per employee per month)::

        Año-Mes,EMPRESA,EMPLEADO,NOMBRE,CENTRO DE COSTO,COD CENTRO DE COSTO
        2025-01,FIBERLINE,44825996,PASACHE SAMAME ...,COMERCIAL II,200.101.02
        2025-01,ROP,74059735,ABURTO VICUÑA ...,LEGAL,300.101.03

    Processing:
    - Rows where EMPRESA = 'ROP' are skipped (not a valid company).
    - If ``cia`` is provided, only rows matching that EMPRESA are kept.
      If ``cia`` is None, all non-ROP companies are processed.
    - Headcount = count of distinct EMPLEADO values per (EMPRESA, COD CENTRO DE COSTO, Año-Mes).
    """
    reader = csv.reader(io.StringIO(csv_content))
    header = next(reader, None)
    if header is None:
        return 0

    col_map = _detect_roster_columns(header)

    # Collect unique employees per (empresa, ceco, year_month)
    # Key: (empresa, ceco_code, year_month_int) → set of empleado IDs
    groups: dict[tuple[str, str, int], set[str]] = {}

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

        if not empleado or not ceco_code or not ano_mes:
            continue

        m = _YEAR_MONTH_RE.match(ano_mes)
        if not m:
            continue
        ym = int(m.group(1)) * 100 + int(m.group(2))

        key = (empresa, ceco_code, ym)
        if key not in groups:
            groups[key] = set()
        groups[key].add(empleado)

    # Convert to headcount records
    records: list[dict] = []
    for (empresa, ceco_code, ym), empleados in groups.items():
        count = len(empleados)
        if count <= 0:
            continue
        records.append({
            "cia": empresa,
            "centro_costo": ceco_code,
            "year_month": ym,
            "headcount": count,
        })

    saved = bulk_upsert(db_path, records)
    # Invalidate cache for all affected companies/years
    for empresa_key in {r["cia"] for r in records}:
        _invalidate_years(empresa_key, records)
    logger.info("CSV roster import: %d headcount records saved from %d employee groups", saved, len(groups))
    return saved


def delete_headcount_entry(
    db_path: str, cia: str, centro_costo: str, year_month: int
) -> bool:
    """Delete a single entry and invalidate cache."""
    deleted = delete_headcount(db_path, cia, centro_costo, year_month)
    year = year_month // 100
    _cache.pop(cia, year)
    return deleted


def invalidate_headcount_cache(cia: str | None = None, year: int | None = None) -> None:
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
        # Try positional fallback: A=año-mes, B=empresa, C=empleado, F=cod centro de costo
        if len(header) >= 6:
            result.setdefault("ano_mes", 0)
            result.setdefault("empresa", 1)
            result.setdefault("empleado", 2)
            result.setdefault("ceco_code", 5)
        else:
            raise ValueError(
                f"Could not detect required columns: {missing}. "
                f"Expected headers: Año-Mes, EMPRESA, EMPLEADO, COD CENTRO DE COSTO"
            )
    return result


def _invalidate_years(cia: str, records: list[dict]) -> None:
    """Invalidate cache for all years covered by the records."""
    years = {r["year_month"] // 100 for r in records if "year_month" in r}
    for y in years:
        _cache.pop(cia, y)
