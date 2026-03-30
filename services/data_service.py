"""Data service — single fetch, transforms P&L + BS, returns JSON-ready dicts.

Used by the web API to load all report data in one call.  Reuses the same
fetch and transform pipeline as the CLI/export path.
"""

import logging
import time
import threading
from collections import OrderedDict

import numpy as np
import pandas as pd

from data.fetcher import fetch_all_data
from accounting.transforms import (
    prepare_pnl, filter_for_statements, assign_partida_pl,
    prepare_bs_stmt,
)
from accounting.aggregation import (
    preaggregate, sales_details, proyectos_especiales,
    detail_by_ceco, detail_resultado_financiero,
)
from accounting.statements import pl_summary, bs_summary
from excel.builder import build_excel_data, build_bs_data
from config.calendar import MONTH_NAMES, MONTH_NAMES_LIST, MONTH_NAMES_SET
from config.company import VALID_COMPANIES
from config.fields import (
    ASIENTO, CUENTA_CONTABLE, DESCRIPCION, NIT, RAZON_SOCIAL,
    CENTRO_COSTO, DESC_CECO, FECHA, SALDO, PARTIDA_PL, MES,
)

logger = logging.getLogger("flxcontabilidad.data_service")


# ── In-memory cache ─────────────────────────────────────────────────────
# Keyed by (company, year). Each entry holds the transformed data + timestamp.
# Protected by a lock for thread safety (gunicorn sync workers are separate
# processes, so this is per-worker, which is fine).
#
# Bounded LRU + TTL: each store holds at most _CACHE_MAX_ENTRIES items.
# Oldest entries are evicted when the limit is reached.

MEMORY_CACHE_TTL = 1800  # 30 minutes
_CACHE_MAX_ENTRIES = 20  # per store (4 companies × 5 years is a reasonable max)

_cache_lock = threading.Lock()
_STORES: dict[str, OrderedDict[tuple[str, int], tuple[float, object]]] = {
    "result": OrderedDict(),
    "df": OrderedDict(),
    "bs": OrderedDict(),
    "raw": OrderedDict(),
}

# Cache observability — simple hit/miss counters per store
_cache_stats: dict[str, dict[str, int]] = {
    store: {"hits": 0, "misses": 0} for store in _STORES
}


def _get_from_cache(store: str, company: str, year: int):
    """Return cached value from *store* or None if missing/expired."""
    key = (company, year)
    with _cache_lock:
        entry = _STORES[store].get(key)
        if entry is None:
            _cache_stats[store]["misses"] += 1
            return None
        if (time.time() - entry[0]) < MEMORY_CACHE_TTL:
            _STORES[store].move_to_end(key)  # mark as recently used
            _cache_stats[store]["hits"] += 1
            return entry[1]
        _cache_stats[store]["misses"] += 1  # expired = miss
        del _STORES[store][key]
    return None


def _set_in_cache(store: str, company: str, year: int, value) -> None:
    """Store *value* in *store* with current timestamp, evicting LRU if full."""
    key = (company, year)
    with _cache_lock:
        if key in _STORES[store]:
            _STORES[store].move_to_end(key)
        _STORES[store][key] = (time.time(), value)
        while len(_STORES[store]) > _CACHE_MAX_ENTRIES:
            _STORES[store].popitem(last=False)  # evict oldest


# Public accessors used by routes.py
def get_bs_cached(company: str, year: int) -> pd.DataFrame | None:
    """Return cached prepared BS DataFrame or None."""
    return _get_from_cache("bs", company, year)


def get_raw_cached(company: str, year: int) -> tuple | None:
    """Return cached raw DataFrames or None."""
    return _get_from_cache("raw", company, year)


def get_cache_stats() -> dict:
    """Return cache hit/miss counters and current entry counts per store."""
    with _cache_lock:
        return {
            store: {
                "hits": _cache_stats[store]["hits"],
                "misses": _cache_stats[store]["misses"],
                "entries": len(_STORES[store]),
            }
            for store in _STORES
        }


def invalidate_cache(company: str | None = None, year: int | None = None) -> None:
    """Clear cache entries. If both args are given, clear only that key."""
    with _cache_lock:
        if company and year:
            key = (company, year)
            for store in _STORES.values():
                store.pop(key, None)
        else:
            for store in _STORES.values():
                store.clear()


# ── DataFrame → JSON helpers ────────────────────────────────────────────

def _sanitize_value(v):
    """Convert numpy/pandas types to JSON-safe Python types."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return round(float(v), 2)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    return v


def _df_to_records(df: pd.DataFrame) -> list[dict]:
    """Convert a DataFrame to a list of dicts with sanitized values."""
    records = df.to_dict(orient="records")
    return [
        {k: _sanitize_value(v) for k, v in row.items()}
        for row in records
    ]


# ── Main entry point ────────────────────────────────────────────────────

def load_report_data(company: str, year: int, *, force_refresh: bool = False) -> dict:
    """Fetch and transform all report data for a company/year.

    Returns a dict with:
        - pl_summary: list of row dicts (P&L, 12 months + TOTAL)
        - bs_summary: list of row dicts (BS, 12 months cumulative)
        - company: str
        - year: int
        - months: list of month column names
    """
    if company not in VALID_COMPANIES:
        raise ValueError(f"Unknown company: {company!r}")

    if not force_refresh:
        cached = _get_from_cache("result", company, year)
        if cached:
            logger.info("Serving cached data for %s/%d", company, year)
            return cached

    t0 = time.perf_counter()

    # Single fetch — gets P&L + BS + previous year data
    raw, raw_current_full, raw_prev, raw_bs, raw_bs_prev = fetch_all_data(
        company, year, None, need_pdf=False,
    )

    logger.info("Data fetch: %.2fs (%d PnL rows, %d BS rows)", time.perf_counter() - t0, len(raw_current_full), len(raw_bs))

    t1 = time.perf_counter()

    # P&L transforms
    df_pnl = prepare_pnl(raw_current_full)
    df_stmt = filter_for_statements(df_pnl)
    df_stmt = assign_partida_pl(df_stmt)
    pl = pl_summary(df_stmt)

    # Ensure P&L has all 12 month columns in calendar order (missing filled with 0)
    non_month_cols = [c for c in pl.columns if c not in MONTH_NAMES_SET]
    pl = pl.reindex(columns=non_month_cols + MONTH_NAMES_LIST, fill_value=0)

    # BS transforms — no month filtering; cumsum carries balances forward naturally
    df_bs = prepare_bs_stmt(raw_bs) if not raw_bs.empty else None
    if df_bs is not None:
        bs = bs_summary(df_bs, include_detail=False, pl_summary_df=pl)
    else:
        bs = pd.DataFrame()

    # Ingresos detail pivots (reuse df_stmt which has NIT/RAZON_SOCIAL)
    preagg = preaggregate(df_stmt)
    sd = sales_details(df_stmt, with_total_row=True, preagg=preagg)
    pe = proyectos_especiales(df_stmt, MONTH_NAMES_LIST, with_total_row=True)

    # P&L note detail pivots (by CECO)
    costo = detail_by_ceco(df_stmt, ["COSTO"], with_total_row=True, preagg=preagg)
    gasto_venta = detail_by_ceco(df_stmt, ["GASTO VENTA"], with_total_row=True, preagg=preagg)
    gasto_admin = detail_by_ceco(df_stmt, ["GASTO ADMIN"], with_total_row=True, preagg=preagg)
    dya_costo = detail_by_ceco(df_stmt, ["D&A - COSTO"], with_total_row=True, preagg=preagg)
    dya_gasto = detail_by_ceco(df_stmt, ["D&A - GASTO"], with_total_row=True, preagg=preagg)

    # Resultado Financiero (split into ingresos/gastos by cuenta)
    res_fin = detail_resultado_financiero(df_stmt, preagg=preagg)

    logger.info("Transforms: %.2fs", time.perf_counter() - t1)

    months = MONTH_NAMES_LIST

    result = {
        "pl_summary": _df_to_records(pl),
        "bs_summary": _df_to_records(bs),
        "ingresos_ordinarios": _df_to_records(sd),
        "ingresos_proyectos": _df_to_records(pe),
        "costo": _df_to_records(costo),
        "gasto_venta": _df_to_records(gasto_venta),
        "gasto_admin": _df_to_records(gasto_admin),
        "dya_costo": _df_to_records(dya_costo),
        "dya_gasto": _df_to_records(dya_gasto),
        "resultado_financiero_ingresos": _df_to_records(res_fin.ingresos),
        "resultado_financiero_gastos": _df_to_records(res_fin.gastos),
        "company": company,
        "year": year,
        "months": months,
    }

    _set_in_cache("result", company, year, result)
    _set_in_cache("df", company, year, df_stmt)
    if df_bs is not None:
        _set_in_cache("bs", company, year, df_bs)
    _set_in_cache("raw", company, year, (raw, raw_current_full, raw_prev, raw_bs, raw_bs_prev))
    logger.info("Total load_report_data: %.2fs", time.perf_counter() - t0)

    return result


# ── Detail drill-down ──────────────────────────────────────────────────

# Columns to expose in the detail view
_DETAIL_COLUMNS = [
    ASIENTO, CUENTA_CONTABLE, DESCRIPCION, NIT, RAZON_SOCIAL,
    CENTRO_COSTO, DESC_CECO, FECHA, SALDO,
]

# Columns allowed for client-side filtering (excludes FECHA/SALDO)
_FILTERABLE_COLUMNS = frozenset(_DETAIL_COLUMNS) - {FECHA, SALDO}

# Reverse lookup: month name → month number
_MONTH_NAME_TO_NUM = {v: k for k, v in MONTH_NAMES.items()}


def get_detail_records(
    company: str, year: int, partida: str, month: str | None = None,
    filter_col: str | None = None, filter_val: str | None = None,
) -> list[dict]:
    """Return raw journal entries matching the given partida + optional month/filter.

    If month is None, returns records for all months (full period).
    If the data hasn't been loaded yet, triggers a load first.
    """
    df = _get_from_cache("df", company, year)
    if df is None:
        # Force a load to populate the df cache
        load_report_data(company, year, force_refresh=True)
        df = _get_from_cache("df", company, year)
        if df is None:
            return []

    mask = df[PARTIDA_PL] == partida

    if month is not None:
        month_num = _MONTH_NAME_TO_NUM.get(month)
        if month_num is None:
            return []
        mask = mask & (df[MES] == month_num)

    if filter_col and filter_val is not None:
        if filter_col not in _FILTERABLE_COLUMNS:
            return []
        mask = mask & (df[filter_col].astype(str) == filter_val)

    result = df.loc[mask, _DETAIL_COLUMNS].copy()
    result[FECHA] = result[FECHA].dt.strftime("%Y-%m-%d")
    result = result.sort_values(SALDO, ascending=False).reset_index(drop=True)
    return _df_to_records(result)
