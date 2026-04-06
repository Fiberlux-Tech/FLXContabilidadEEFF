"""Data service — single fetch, transforms P&L + BS, returns JSON-ready dicts.

Used by the web API to load all report data in one call.  Reuses the same
fetch and transform pipeline as the CLI/export path.

Split endpoints (load_pl_data / load_bs_data) allow the dashboard to fetch
P&L first (fast) and defer BS until the user needs it, with background
pre-fetching to warm the cache.
"""

import logging
import time
import threading
from collections import OrderedDict

import numpy as np
import pandas as pd

from data.fetcher import fetch_all_data, fetch_pnl_only, fetch_bs_only
from accounting.transforms import prepare_stmt, prepare_bs_stmt
from accounting.aggregation import (
    ensure_month_columns, preaggregate, sales_details,
    proyectos_especiales,
    detail_by_ceco, detail_by_cuenta, detail_ceco_by_cuenta,
    detail_resultado_financiero, detail_planilla,
    detail_proveedores_transporte,
    bs_detail_by_cuenta, bs_top20_by_nit, append_total_row,
)
from accounting.statements import pl_summary, bs_summary
from accounting.notes import BS_DETAIL_ENTRIES
from excel.builder import build_excel_data, build_bs_data
from config.calendar import MONTH_NAMES, MONTH_NAMES_LIST
from config.company import VALID_COMPANIES
from config.fields import (
    ASIENTO, CUENTA_CONTABLE, DESCRIPCION, NIT, RAZON_SOCIAL,
    CENTRO_COSTO, DESC_CECO, FECHA, SALDO, PARTIDA_PL, PARTIDA_BS, MES,
    IS_INTERCOMPANY,
)

logger = logging.getLogger("flxcontabilidad.data_service")


# ── In-memory LRU+TTL cache ──────────────────────────────────────────────

class LRUTTLCache:
    """Thread-safe LRU cache with per-entry TTL expiration.

    Keyed by (company, year) tuples. Each entry holds transformed data + timestamp.
    """

    def __init__(self, name: str, ttl: int = 1800, max_entries: int = 20):
        self.name = name
        self.ttl = ttl
        self.max_entries = max_entries
        self._store: OrderedDict[tuple[str, int], tuple[float, object]] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, company: str, year: int):
        """Return cached value or None if missing/expired."""
        key = (company, year)
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self.misses += 1
                return None
            if (time.time() - entry[0]) < self.ttl:
                self._store.move_to_end(key)
                self.hits += 1
                return entry[1]
            self.misses += 1
            del self._store[key]
        return None

    def set(self, company: str, year: int, value) -> None:
        """Store value with current timestamp, evicting LRU if full."""
        key = (company, year)
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
            self._store[key] = (time.time(), value)
            while len(self._store) > self.max_entries:
                self._store.popitem(last=False)

    def pop(self, company: str, year: int) -> None:
        """Remove a specific entry if it exists."""
        key = (company, year)
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        """Remove all entries."""
        with self._lock:
            self._store.clear()

    def stats(self) -> dict:
        """Return hit/miss counters and current entry count."""
        with self._lock:
            return {"hits": self.hits, "misses": self.misses, "entries": len(self._store)}


_caches: dict[str, LRUTTLCache] = {
    "result": LRUTTLCache("result"),
    "df": LRUTTLCache("df"),
    "bs": LRUTTLCache("bs"),
    "raw": LRUTTLCache("raw"),
    "pl_result": LRUTTLCache("pl_result"),
    "bs_result": LRUTTLCache("bs_result"),
    "pl_df": LRUTTLCache("pl_df"),
}


# Public accessors used by routes.py
def get_bs_cached(company: str, year: int) -> pd.DataFrame | None:
    """Return cached prepared BS DataFrame or None."""
    return _caches["bs"].get(company, year)


def get_raw_cached(company: str, year: int) -> tuple | None:
    """Return cached raw DataFrames or None."""
    return _caches["raw"].get(company, year)


def get_cache_stats() -> dict:
    """Return cache hit/miss counters and current entry counts per store."""
    return {name: cache.stats() for name, cache in _caches.items()}


def invalidate_cache(company: str | None = None, year: int | None = None) -> None:
    """Clear cache entries. If both args are given, clear only that key."""
    if company and year:
        for cache in _caches.values():
            cache.pop(company, year)
    else:
        for cache in _caches.values():
            cache.clear()


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
        cached = _caches["result"].get(company, year)
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

    # P&L transforms — reuse _run_pl_transforms (shared with load_pl_data)
    df_stmt, pl, pl_records = _run_pl_transforms(raw_current_full)

    # BS transforms — no month filtering; cumsum carries balances forward naturally
    df_bs = prepare_bs_stmt(raw_bs) if not raw_bs.empty else None
    if df_bs is not None:
        bs = bs_summary(df_bs, include_detail=False, pl_summary_df=pl)
    else:
        bs = pd.DataFrame()

    logger.info("Transforms: %.2fs", time.perf_counter() - t1)

    result = {
        **pl_records,
        "bs_summary": _df_to_records(bs),
        "company": company,
        "year": year,
        "months": MONTH_NAMES_LIST,
    }

    _caches["result"].set(company, year, result)
    _caches["df"].set(company, year, df_stmt)
    if df_bs is not None:
        _caches["bs"].set(company, year, df_bs)
    _caches["raw"].set(company, year, (raw, raw_current_full, raw_prev, raw_bs, raw_bs_prev))

    # Cross-populate split caches so split endpoints get instant hits
    _caches["pl_df"].set(company, year, pl)
    _caches["pl_result"].set(company, year, {k: v for k, v in result.items() if k != "bs_summary"})
    _caches["bs_result"].set(company, year, {
        "bs_summary": result["bs_summary"], "company": company, "year": year, "months": MONTH_NAMES_LIST,
    })

    logger.info("Total load_report_data: %.2fs", time.perf_counter() - t0)

    return result


# ── Split P&L / BS loading (fast dashboard path) ──────────────────────

def _run_pl_transforms(raw_current_full: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Run P&L transform pipeline.  Returns (df_stmt, pl_df, pl_records_dict)."""
    df_stmt = prepare_stmt(raw_current_full)
    pl = pl_summary(df_stmt)
    # Excluding-intercompany summary: filter out IS_INTERCOMPANY rows and re-pivot
    pl_ex_ic = pl_summary(df_stmt[~df_stmt[IS_INTERCOMPANY]])
    # Only-intercompany summary: keep only IS_INTERCOMPANY rows
    pl_only_ic = pl_summary(df_stmt[df_stmt[IS_INTERCOMPANY]])

    pl = ensure_month_columns(pl)
    pl_ex_ic = ensure_month_columns(pl_ex_ic)
    pl_only_ic = ensure_month_columns(pl_only_ic)

    preagg = preaggregate(df_stmt)
    sd = sales_details(df_stmt, with_total_row=True, preagg=preagg)
    pe = proyectos_especiales(df_stmt, MONTH_NAMES_LIST, with_total_row=True)
    costo = detail_by_ceco(df_stmt, ["COSTO"], with_total_row=True, preagg=preagg)
    costo_by_cuenta = detail_ceco_by_cuenta(df_stmt, ["COSTO"], preagg=preagg)
    gasto_venta = detail_by_ceco(df_stmt, ["GASTO VENTA"], with_total_row=True, preagg=preagg)
    gasto_venta_by_cuenta = detail_by_cuenta(df_stmt, ["GASTO VENTA"], preagg=preagg)
    gasto_admin = detail_by_ceco(df_stmt, ["GASTO ADMIN"], with_total_row=True, preagg=preagg)
    gasto_admin_by_cuenta = detail_by_cuenta(df_stmt, ["GASTO ADMIN"], preagg=preagg)
    dya_costo = detail_by_ceco(df_stmt, ["D&A - COSTO"], with_total_row=True, preagg=preagg)
    dya_costo_by_cuenta = detail_by_cuenta(df_stmt, ["D&A - COSTO"], preagg=preagg)
    dya_gasto = detail_by_ceco(df_stmt, ["D&A - GASTO"], with_total_row=True, preagg=preagg)
    dya_gasto_by_cuenta = detail_by_cuenta(df_stmt, ["D&A - GASTO"], preagg=preagg)
    res_fin = detail_resultado_financiero(df_stmt, preagg=preagg)
    otros_ingresos = detail_by_cuenta(df_stmt, ["OTROS INGRESOS"], with_total_row=True, preagg=preagg)
    otros_ingresos_by_cuenta = detail_by_cuenta(df_stmt, ["OTROS INGRESOS"], preagg=preagg)
    participacion_by_cuenta = detail_by_cuenta(df_stmt, ["PARTICIPACION DE TRABAJADORES"], preagg=preagg)
    provision_by_cuenta = detail_by_cuenta(df_stmt, ["PROVISION INCOBRABLE"], preagg=preagg)
    otros_egresos = detail_by_cuenta(df_stmt, ["OTROS EGRESOS"], with_total_row=True, preagg=preagg)
    otros_egresos_by_cuenta = detail_by_cuenta(df_stmt, ["OTROS EGRESOS"], preagg=preagg)
    planilla_by_cuenta = detail_planilla(df_stmt, preagg=preagg)
    proveedores_transporte = detail_proveedores_transporte(df_stmt)

    records = {
        "pl_summary": _df_to_records(pl),
        "pl_summary_ex_ic": _df_to_records(pl_ex_ic),
        "pl_summary_only_ic": _df_to_records(pl_only_ic),
        "ingresos_ordinarios": _df_to_records(sd),
        "ingresos_proyectos": _df_to_records(pe),
        "costo": _df_to_records(costo),
        "costo_by_cuenta": _df_to_records(costo_by_cuenta),
        "gasto_venta": _df_to_records(gasto_venta),
        "gasto_venta_by_cuenta": _df_to_records(gasto_venta_by_cuenta),
        "gasto_admin": _df_to_records(gasto_admin),
        "gasto_admin_by_cuenta": _df_to_records(gasto_admin_by_cuenta),
        "dya_costo": _df_to_records(dya_costo),
        "dya_costo_by_cuenta": _df_to_records(dya_costo_by_cuenta),
        "dya_gasto": _df_to_records(dya_gasto),
        "dya_gasto_by_cuenta": _df_to_records(dya_gasto_by_cuenta),
        "resultado_financiero_ingresos": _df_to_records(res_fin.ingresos),
        "resultado_financiero_gastos": _df_to_records(res_fin.gastos),
        "otros_ingresos": _df_to_records(otros_ingresos),
        "otros_ingresos_by_cuenta": _df_to_records(otros_ingresos_by_cuenta),
        "participacion_by_cuenta": _df_to_records(participacion_by_cuenta),
        "provision_by_cuenta": _df_to_records(provision_by_cuenta),
        "otros_egresos": _df_to_records(otros_egresos),
        "otros_egresos_by_cuenta": _df_to_records(otros_egresos_by_cuenta),
        "planilla_by_cuenta": _df_to_records(planilla_by_cuenta),
        "proveedores_transporte": _df_to_records(proveedores_transporte),
    }
    return df_stmt, pl, records


def load_pl_data(company: str, year: int, *, force_refresh: bool = False) -> dict:
    """Fetch and transform P&L data only.  BS is pre-fetched in the background.

    Returns the same shape as load_report_data minus bs_summary.
    """
    if company not in VALID_COMPANIES:
        raise ValueError(f"Unknown company: {company!r}")

    if not force_refresh:
        cached = _caches["pl_result"].get(company, year)
        if cached:
            logger.info("Serving cached P&L data for %s/%d", company, year)
            return cached
        # If a full load was done before, extract P&L from it
        full = _caches["result"].get(company, year)
        if full:
            logger.info("Serving P&L from full cache for %s/%d", company, year)
            pl_result = {k: v for k, v in full.items() if k != "bs_summary"}
            _caches["pl_result"].set(company, year, pl_result)
            return pl_result

    t0 = time.perf_counter()

    raw_current_full = fetch_pnl_only(company, year)
    logger.info("P&L fetch: %.2fs (%d rows)", time.perf_counter() - t0, len(raw_current_full))

    t1 = time.perf_counter()
    df_stmt, pl, records = _run_pl_transforms(raw_current_full)
    logger.info("P&L transforms: %.2fs", time.perf_counter() - t1)

    result = {
        **records,
        "company": company,
        "year": year,
        "months": MONTH_NAMES_LIST,
    }

    _caches["pl_result"].set(company, year, result)
    _caches["pl_df"].set(company, year, pl)
    _caches["df"].set(company, year, df_stmt)
    logger.info("Total load_pl_data: %.2fs", time.perf_counter() - t0)

    # Pre-fetch BS in background so it's ready when the user needs it
    _prefetch_bs_background(company, year)

    return result


def load_bs_data(company: str, year: int, *, force_refresh: bool = False) -> dict:
    """Fetch and transform BS data.  Requires P&L to have been loaded first
    (for UTILIDAD NETA injection into PATRIMONIO).

    If P&L is not cached, loads it first as a safety net.
    """
    if company not in VALID_COMPANIES:
        raise ValueError(f"Unknown company: {company!r}")

    if not force_refresh:
        cached = _caches["bs_result"].get(company, year)
        if cached:
            logger.info("Serving cached BS data for %s/%d", company, year)
            return cached
        full = _caches["result"].get(company, year)
        if full:
            logger.info("Serving BS from full cache for %s/%d", company, year)
            # The old full cache may not have BS detail keys — fall through
            # to recompute if it only has bs_summary
            if "bs_efectivo" in full:
                bs_result = {k: v for k, v in full.items()
                             if k == "bs_summary" or k.startswith("bs_") or k in ("company", "year", "months")}
                _caches["bs_result"].set(company, year, bs_result)
                return bs_result

    t0 = time.perf_counter()

    # Ensure P&L summary is available (needed for Resultados del Ejercicio)
    pl_df = _caches["pl_df"].get(company, year)
    if pl_df is None:
        logger.info("P&L not cached for %s/%d — loading first (BS dependency)", company, year)
        load_pl_data(company, year)
        pl_df = _caches["pl_df"].get(company, year)

    raw_bs = fetch_bs_only(company, year)
    logger.info("BS fetch: %.2fs (%d rows)", time.perf_counter() - t0, len(raw_bs))

    t1 = time.perf_counter()
    if not raw_bs.empty:
        df_bs = prepare_bs_stmt(raw_bs)
        bs = bs_summary(df_bs, include_detail=False, pl_summary_df=pl_df)
    else:
        df_bs = None
        bs = pd.DataFrame()
    logger.info("BS transforms: %.2fs", time.perf_counter() - t1)

    result = {
        "bs_summary": _df_to_records(bs),
        "company": company,
        "year": year,
        "months": MONTH_NAMES_LIST,
    }

    # BS note detail tables (reuse the same aggregation functions as Excel/PDF)
    if df_bs is not None:
        for key, partidas, include_pf, exclude_pf in BS_DETAIL_ENTRIES:
            detail = bs_detail_by_cuenta(
                df_bs, partidas,
                cuenta_prefixes=include_pf,
                exclude_cuenta_prefixes=exclude_pf,
            )
            detail = append_total_row(detail, DESCRIPCION)
            result[key] = _df_to_records(detail)

        # NIT top-20 ranking tables
        _BS_NIT_RANKINGS = [
            ("bs_cxc_comerciales_nit_top20", ["Cuentas por cobrar comerciales (neto)"]),
            ("bs_cxc_otras_nit_top20",       ["Otras cuentas por cobrar (neto)"]),
            ("bs_cxp_comerciales_nit_top20", ["Cuentas por pagar comerciales"]),
            ("bs_cxp_otras_nit_top20",       ["Otras cuentas por pagar"]),
        ]
        for key, partidas in _BS_NIT_RANKINGS:
            result[key] = _df_to_records(bs_top20_by_nit(df_bs, partidas))

    _caches["bs_result"].set(company, year, result)
    if df_bs is not None:
        _caches["bs"].set(company, year, df_bs)
    logger.info("Total load_bs_data: %.2fs", time.perf_counter() - t0)

    return result


# ── Background BS pre-fetch ───────────────────────────────────────────

_bg_lock = threading.Lock()
_bg_tasks: dict[tuple[str, int], threading.Thread] = {}


def _prefetch_bs_background(company: str, year: int) -> None:
    """Spawn a daemon thread to pre-fetch BS data so it's cached when needed."""
    key = (company, year)
    with _bg_lock:
        # Already cached or already in flight — skip
        if _caches["bs_result"].get(company, year) is not None:
            return
        existing = _bg_tasks.get(key)
        if existing is not None and existing.is_alive():
            return

        def worker():
            try:
                load_bs_data(company, year)
                logger.info("Background BS pre-fetch done for %s/%d", company, year)
            except Exception:
                logger.exception("Background BS pre-fetch failed for %s/%d", company, year)
            finally:
                with _bg_lock:
                    _bg_tasks.pop(key, None)

        t = threading.Thread(target=worker, daemon=True)
        _bg_tasks[key] = t
        t.start()


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
    Checks P&L data first; if no match, falls back to BS data.
    """
    # Try P&L first
    df = _caches["df"].get(company, year)
    if df is None:
        load_pl_data(company, year, force_refresh=True)
        df = _caches["df"].get(company, year)

    partida_col = PARTIDA_PL
    if df is not None and (df[PARTIDA_PL] == partida).any():
        pass  # use P&L df
    else:
        # Fall back to BS
        df_bs = _caches["bs"].get(company, year)
        if df_bs is None:
            load_bs_data(company, year, force_refresh=True)
            df_bs = _caches["bs"].get(company, year)
        if df_bs is not None:
            df = df_bs
            partida_col = PARTIDA_BS
        elif df is None:
            return []

    mask = df[partida_col] == partida

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
