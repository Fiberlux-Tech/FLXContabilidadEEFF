"""Data service — single fetch, transforms P&L + BS, returns JSON-ready dicts.

Used by the web API to load all report data in one call.  Reuses the same
fetch and transform pipeline as the CLI/export path.

Split endpoints (load_pl_data / load_bs_data) allow the dashboard to fetch
P&L first (fast) and defer BS until the user needs it, with background
pre-fetching to warm the cache.

Detail P&L sections (ingresos, costo, etc.) are computed lazily via
load_pl_section() — only when the user navigates to that view.
"""

import logging
import time
import threading
from collections import OrderedDict
from pathlib import Path

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
from config.calendar import MONTH_NAMES, MONTH_NAMES_LIST, MIN_YEAR
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
    "pl_stmt": LRUTTLCache("pl_stmt"),
    "pl_preagg": LRUTTLCache("pl_preagg"),
    "pl_sections": LRUTTLCache("pl_sections"),
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
        _delete_disk_cache(company, year)
    else:
        for cache in _caches.values():
            cache.clear()
        _clear_all_disk_cache()


# ── Disk cache for df_stmt (survives restarts) ────────────────────────

_STMT_CACHE_DIR = Path(__file__).parent / ".stmt_cache"
_DISK_CACHE_TTL = 30 * 24 * 3600  # 30 days


def _stmt_disk_path(company: str, year: int, kind: str = "df_stmt") -> Path:
    return _STMT_CACHE_DIR / f"{kind}_{company}_{year}.pkl"


def _load_from_disk(company: str, year: int, kind: str = "df_stmt") -> pd.DataFrame | None:
    """Load a cached DataFrame from disk if available and not expired."""
    path = _stmt_disk_path(company, year, kind)
    if not path.exists():
        return None
    age = time.time() - path.stat().st_mtime
    if age > _DISK_CACHE_TTL:
        path.unlink(missing_ok=True)
        return None
    try:
        df = pd.read_pickle(path)
        logger.info("Loaded %s from disk cache: %s", kind, path.name)
        return df
    except Exception:
        logger.warning("Disk cache corrupted, will re-fetch: %s", path.name)
        path.unlink(missing_ok=True)
        return None


def _save_to_disk(company: str, year: int, df: pd.DataFrame, kind: str = "df_stmt") -> None:
    """Persist a DataFrame to disk cache."""
    _STMT_CACHE_DIR.mkdir(exist_ok=True)
    path = _stmt_disk_path(company, year, kind)
    try:
        df.to_pickle(path)
        size_mb = path.stat().st_size / 1e6
        logger.info("Saved %s to disk cache: %s (%.1fMB)", kind, path.name, size_mb)
    except Exception:
        logger.warning("Failed to write disk cache: %s", path.name)


def _delete_disk_cache(company: str, year: int) -> None:
    """Delete disk cache files for a specific company/year."""
    for kind in ("df_stmt", "preagg"):
        path = _stmt_disk_path(company, year, kind)
        path.unlink(missing_ok=True)


def _clear_all_disk_cache() -> None:
    """Delete all disk cache files."""
    if _STMT_CACHE_DIR.exists():
        for f in _STMT_CACHE_DIR.glob("*.pkl"):
            f.unlink(missing_ok=True)


# ── IC-filtered variant helper ───────────────────────────────────────
#
# Produces _ex_ic / _only_ic variants of each detail table.
# The filtered variants are reindexed to match the "all" table's row
# structure so the frontend always sees the same rows (with zeros where
# the filter excludes data).


def _reindex_like(filtered: pd.DataFrame, reference: pd.DataFrame) -> pd.DataFrame:
    """Reindex *filtered* to have the same rows as *reference*, filling gaps with 0/None.

    Label columns are preserved from *reference*; numeric month columns
    default to 0 so the table shape is identical regardless of filter.
    """
    if filtered.empty or reference.empty:
        # Return reference structure with zeroed numerics
        result = reference.copy()
        for col in result.select_dtypes(include="number").columns:
            result[col] = 0
        return result

    # Identify label vs numeric columns from reference
    num_cols = list(reference.select_dtypes(include="number").columns)
    label_cols = [c for c in reference.columns if c not in num_cols]

    # Build a lookup from label values → filtered numeric values
    if label_cols:
        # Create composite key for matching
        ref_keys = reference[label_cols].astype(str).apply("|".join, axis=1)
        filt_keys = filtered[label_cols].astype(str).apply("|".join, axis=1)
        filt_lookup = dict(zip(filt_keys, filtered.index))
    else:
        ref_keys = reference.index
        filt_lookup = {}

    result = reference.copy()
    for col in num_cols:
        result[col] = 0.0

    for i, key in enumerate(ref_keys):
        if key in filt_lookup:
            src_idx = filt_lookup[key]
            for col in num_cols:
                result.at[i, col] = filtered.at[src_idx, col]

    return result


def _add_ic_variants(base: dict[str, pd.DataFrame],
                     df_stmt: pd.DataFrame,
                     preagg: pd.DataFrame,
                     compute_fn) -> dict[str, pd.DataFrame]:
    """Run *compute_fn* on IC-filtered subsets and merge results with *base*.

    For each key in *base*, adds key_ex_ic and key_only_ic variants
    reindexed to match the original row structure.
    """
    df_ex_ic = df_stmt[~df_stmt[IS_INTERCOMPANY]]
    df_only_ic = df_stmt[df_stmt[IS_INTERCOMPANY]]

    # Re-preaggregate from filtered df_stmt (preagg doesn't carry IS_INTERCOMPANY)
    preagg_ex_ic = preaggregate(df_ex_ic)
    preagg_only_ic = preaggregate(df_only_ic)

    ex_ic_dfs = compute_fn(df_ex_ic, preagg_ex_ic)
    only_ic_dfs = compute_fn(df_only_ic, preagg_only_ic)

    result = dict(base)
    for key, ref_df in base.items():
        ex_df = ex_ic_dfs.get(key, pd.DataFrame())
        ic_df = only_ic_dfs.get(key, pd.DataFrame())
        result[f"{key}_ex_ic"] = _reindex_like(ex_df, ref_df)
        result[f"{key}_only_ic"] = _reindex_like(ic_df, ref_df)

    return result


# ── P&L Section registry ──────────────────────────────────────────────
# Maps section name → compute function that takes (df_stmt, preagg)
# and returns {key: DataFrame}.


def _compute_ingresos_base(df_stmt, preagg):
    return {
        "ingresos_ordinarios": sales_details(df_stmt, with_total_row=True, preagg=preagg),
        "ingresos_proyectos": proyectos_especiales(df_stmt, MONTH_NAMES_LIST, with_total_row=True),
    }


def _compute_ingresos(df_stmt, preagg):
    base = _compute_ingresos_base(df_stmt, preagg)
    return _add_ic_variants(base, df_stmt, preagg, _compute_ingresos_base)


def _compute_costo_base(df_stmt, preagg):
    return {
        "costo": detail_by_ceco(df_stmt, ["COSTO"], ascending=True, with_total_row=True, preagg=preagg),
        "costo_by_cuenta": detail_ceco_by_cuenta(df_stmt, ["COSTO"], preagg=preagg),
    }


def _compute_costo(df_stmt, preagg):
    base = _compute_costo_base(df_stmt, preagg)
    return _add_ic_variants(base, df_stmt, preagg, _compute_costo_base)


def _compute_gasto_venta_base(df_stmt, preagg):
    return {
        "gasto_venta": detail_by_ceco(df_stmt, ["GASTO VENTA"], ascending=True, with_total_row=True, preagg=preagg),
        "gasto_venta_by_cuenta": detail_ceco_by_cuenta(df_stmt, ["GASTO VENTA"], preagg=preagg),
    }


def _compute_gasto_venta(df_stmt, preagg):
    base = _compute_gasto_venta_base(df_stmt, preagg)
    return _add_ic_variants(base, df_stmt, preagg, _compute_gasto_venta_base)


def _compute_gasto_admin_base(df_stmt, preagg):
    return {
        "gasto_admin": detail_by_ceco(df_stmt, ["GASTO ADMIN"], ascending=True, with_total_row=True, preagg=preagg),
        "gasto_admin_by_cuenta": detail_ceco_by_cuenta(df_stmt, ["GASTO ADMIN"], preagg=preagg),
    }


def _compute_gasto_admin(df_stmt, preagg):
    base = _compute_gasto_admin_base(df_stmt, preagg)
    return _add_ic_variants(base, df_stmt, preagg, _compute_gasto_admin_base)


def _compute_otros_egresos_base(df_stmt, preagg):
    return {
        "otros_ingresos": detail_by_cuenta(df_stmt, ["OTROS INGRESOS"], with_total_row=True, preagg=preagg),
        "otros_ingresos_by_cuenta": detail_ceco_by_cuenta(df_stmt, ["OTROS INGRESOS"], preagg=preagg),
        "otros_egresos": detail_by_cuenta(df_stmt, ["OTROS EGRESOS"], ascending=True, with_total_row=True, preagg=preagg),
        "otros_egresos_by_cuenta": detail_ceco_by_cuenta(df_stmt, ["OTROS EGRESOS"], preagg=preagg),
        "participacion_by_cuenta": detail_ceco_by_cuenta(df_stmt, ["PARTICIPACION DE TRABAJADORES"], preagg=preagg),
        "provision_by_cuenta": detail_ceco_by_cuenta(df_stmt, ["PROVISION INCOBRABLE"], preagg=preagg),
    }


def _compute_otros_egresos(df_stmt, preagg):
    base = _compute_otros_egresos_base(df_stmt, preagg)
    return _add_ic_variants(base, df_stmt, preagg, _compute_otros_egresos_base)


def _compute_dya_base(df_stmt, preagg):
    return {
        "dya_costo": detail_by_ceco(df_stmt, ["D&A - COSTO"], ascending=True, with_total_row=True, preagg=preagg),
        "dya_costo_by_cuenta": detail_ceco_by_cuenta(df_stmt, ["D&A - COSTO"], preagg=preagg),
        "dya_gasto": detail_by_ceco(df_stmt, ["D&A - GASTO"], ascending=True, with_total_row=True, preagg=preagg),
        "dya_gasto_by_cuenta": detail_ceco_by_cuenta(df_stmt, ["D&A - GASTO"], preagg=preagg),
    }


def _compute_dya(df_stmt, preagg):
    base = _compute_dya_base(df_stmt, preagg)
    return _add_ic_variants(base, df_stmt, preagg, _compute_dya_base)


def _compute_resultado_financiero_base(df_stmt, preagg):
    res = detail_resultado_financiero(df_stmt, preagg=preagg)
    return {
        "resultado_financiero_ingresos": res.ingresos,
        "resultado_financiero_gastos": res.gastos,
    }


def _compute_resultado_financiero(df_stmt, preagg):
    base = _compute_resultado_financiero_base(df_stmt, preagg)
    return _add_ic_variants(base, df_stmt, preagg, _compute_resultado_financiero_base)


def _compute_analysis_pl_finanzas_base(df_stmt, preagg):
    return {
        "costo_by_cuenta": detail_ceco_by_cuenta(df_stmt, ["COSTO"], preagg=preagg),
        "gasto_venta_by_cuenta": detail_ceco_by_cuenta(df_stmt, ["GASTO VENTA"], preagg=preagg),
        "gasto_admin_by_cuenta": detail_ceco_by_cuenta(df_stmt, ["GASTO ADMIN"], preagg=preagg),
        "dya_costo_by_cuenta": detail_ceco_by_cuenta(df_stmt, ["D&A - COSTO"], preagg=preagg),
        "dya_gasto_by_cuenta": detail_ceco_by_cuenta(df_stmt, ["D&A - GASTO"], preagg=preagg),
        "otros_ingresos_by_cuenta": detail_ceco_by_cuenta(df_stmt, ["OTROS INGRESOS"], preagg=preagg),
        "otros_egresos_by_cuenta": detail_ceco_by_cuenta(df_stmt, ["OTROS EGRESOS"], preagg=preagg),
        "participacion_by_cuenta": detail_ceco_by_cuenta(df_stmt, ["PARTICIPACION DE TRABAJADORES"], preagg=preagg),
        "provision_by_cuenta": detail_ceco_by_cuenta(df_stmt, ["PROVISION INCOBRABLE"], preagg=preagg),
    }


def _compute_analysis_pl_finanzas(df_stmt, preagg):
    base = _compute_analysis_pl_finanzas_base(df_stmt, preagg)
    return _add_ic_variants(base, df_stmt, preagg, _compute_analysis_pl_finanzas_base)


def _compute_analysis_planilla(df_stmt, preagg):
    return {
        "planilla_by_cuenta": detail_planilla(df_stmt, preagg=preagg),
    }


def _compute_analysis_proveedores(df_stmt, preagg):
    return {
        "proveedores_transporte": detail_proveedores_transporte(df_stmt),
    }


SECTION_REGISTRY: dict[str, callable] = {
    "ingresos": _compute_ingresos,
    "costo": _compute_costo,
    "gasto_venta": _compute_gasto_venta,
    "gasto_admin": _compute_gasto_admin,
    "otros_egresos": _compute_otros_egresos,
    "dya": _compute_dya,
    "resultado_financiero": _compute_resultado_financiero,
    "analysis_pl_finanzas": _compute_analysis_pl_finanzas,
    "analysis_planilla": _compute_analysis_planilla,
    "analysis_proveedores": _compute_analysis_proveedores,
}

VALID_PL_SECTIONS = frozenset(SECTION_REGISTRY.keys())


def compute_pl_section(df_stmt: pd.DataFrame, preagg: pd.DataFrame,
                       section_name: str) -> dict[str, pd.DataFrame]:
    """Compute a specific P&L detail section from prepared data.

    Returns {key: DataFrame} for the section's tables.
    """
    compute_fn = SECTION_REGISTRY[section_name]
    return compute_fn(df_stmt, preagg)


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
    _caches["pl_stmt"].set(company, year, df_stmt)
    _caches["pl_preagg"].set(company, year, preaggregate(df_stmt))
    if df_bs is not None:
        _caches["bs"].set(company, year, df_bs)
    _caches["raw"].set(company, year, (raw, raw_current_full, raw_prev, raw_bs, raw_bs_prev))

    # Cross-populate split caches so split endpoints get instant hits
    _caches["pl_df"].set(company, year, pl)
    # pl_result for the summary-only fast path
    _caches["pl_result"].set(company, year, {
        "pl_summary": result["pl_summary"],
        "pl_summary_ex_ic": result["pl_summary_ex_ic"],
        "pl_summary_only_ic": result["pl_summary_only_ic"],
        "company": company, "year": year, "months": MONTH_NAMES_LIST,
    })
    _caches["bs_result"].set(company, year, {
        "bs_summary": result["bs_summary"], "company": company, "year": year, "months": MONTH_NAMES_LIST,
    })

    logger.info("Total load_report_data: %.2fs", time.perf_counter() - t0)

    return result


# ── Split P&L / BS loading (fast dashboard path) ──────────────────────

def _run_pl_summary_only(raw_current_full: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    """Fast path: prepare data + compute only P&L summaries (no detail pivots).

    Returns (df_stmt, preagg, pl_df, summary_records_dict).
    """
    df_stmt = prepare_stmt(raw_current_full)
    preagg = preaggregate(df_stmt)

    pl = pl_summary(df_stmt)
    pl_ex_ic = pl_summary(df_stmt[~df_stmt[IS_INTERCOMPANY]])
    pl_only_ic = pl_summary(df_stmt[df_stmt[IS_INTERCOMPANY]])

    pl = ensure_month_columns(pl)
    pl_ex_ic = ensure_month_columns(pl_ex_ic)
    pl_only_ic = ensure_month_columns(pl_only_ic)

    records = {
        "pl_summary": _df_to_records(pl),
        "pl_summary_ex_ic": _df_to_records(pl_ex_ic),
        "pl_summary_only_ic": _df_to_records(pl_only_ic),
    }
    return df_stmt, preagg, pl, records


def _run_pl_transforms(raw_current_full: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Full P&L transform pipeline: summaries + all detail sections.

    Returns (df_stmt, pl_df, all_records_dict).
    Used by load_report_data (exports / full-load path).
    """
    df_stmt, preagg, pl, records = _run_pl_summary_only(raw_current_full)

    # Compute all detail sections
    for section_name in SECTION_REGISTRY:
        section_dfs = compute_pl_section(df_stmt, preagg, section_name)
        for key, df in section_dfs.items():
            if key not in records:  # avoid duplicating keys across sections
                records[key] = _df_to_records(df)

    return df_stmt, pl, records


def _ensure_pl_stmt_cached(company: str, year: int, *, force_refresh: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (df_stmt, preagg) for a company/year, from cache or fresh load.

    Checks: in-memory cache → disk cache → SQL fetch + transform.
    Also populates pl_df cache for BS dependency.
    """
    if not force_refresh:
        df_stmt = _caches["pl_stmt"].get(company, year)
        preagg = _caches["pl_preagg"].get(company, year)
        if df_stmt is not None and preagg is not None:
            return df_stmt, preagg

        # Try disk cache
        df_stmt = _load_from_disk(company, year, "df_stmt")
        if df_stmt is not None:
            preagg = _load_from_disk(company, year, "preagg")
            if preagg is None:
                preagg = preaggregate(df_stmt)
            _caches["pl_stmt"].set(company, year, df_stmt)
            _caches["pl_preagg"].set(company, year, preagg)
            _caches["df"].set(company, year, df_stmt)
            # Also compute and cache pl_df for BS dependency
            pl = pl_summary(df_stmt)
            pl = ensure_month_columns(pl)
            _caches["pl_df"].set(company, year, pl)
            return df_stmt, preagg

    # Full fetch + transform
    t0 = time.perf_counter()
    raw = fetch_pnl_only(company, year)
    logger.info("P&L fetch: %.2fs (%d rows)", time.perf_counter() - t0, len(raw))

    df_stmt, preagg, pl, _ = _run_pl_summary_only(raw)

    _caches["pl_stmt"].set(company, year, df_stmt)
    _caches["pl_preagg"].set(company, year, preagg)
    _caches["df"].set(company, year, df_stmt)
    _caches["pl_df"].set(company, year, pl)

    # Persist to disk for future restarts
    _save_to_disk(company, year, df_stmt, "df_stmt")
    _save_to_disk(company, year, preagg, "preagg")

    return df_stmt, preagg


def load_pl_data(company: str, year: int, *, force_refresh: bool = False) -> dict:
    """Fetch and transform P&L summary only (fast dashboard path).

    Returns only pl_summary + intercompany variants.  Detail sections are
    loaded on demand via load_pl_section().
    """
    if company not in VALID_COMPANIES:
        raise ValueError(f"Unknown company: {company!r}")

    if not force_refresh:
        cached = _caches["pl_result"].get(company, year)
        if cached:
            logger.info("Serving cached P&L data for %s/%d", company, year)
            return cached

    t0 = time.perf_counter()

    if force_refresh:
        _delete_disk_cache(company, year)
        _caches["pl_sections"].pop(company, year)

    df_stmt, preagg = _ensure_pl_stmt_cached(company, year, force_refresh=force_refresh)

    # Compute summaries from cached df_stmt
    pl = pl_summary(df_stmt)
    pl_ex_ic = pl_summary(df_stmt[~df_stmt[IS_INTERCOMPANY]])
    pl_only_ic = pl_summary(df_stmt[df_stmt[IS_INTERCOMPANY]])

    pl = ensure_month_columns(pl)
    pl_ex_ic = ensure_month_columns(pl_ex_ic)
    pl_only_ic = ensure_month_columns(pl_only_ic)

    result = {
        "pl_summary": _df_to_records(pl),
        "pl_summary_ex_ic": _df_to_records(pl_ex_ic),
        "pl_summary_only_ic": _df_to_records(pl_only_ic),
        "company": company,
        "year": year,
        "months": MONTH_NAMES_LIST,
    }

    _caches["pl_result"].set(company, year, result)
    _caches["pl_df"].set(company, year, pl)
    logger.info("Total load_pl_data: %.2fs", time.perf_counter() - t0)

    # Pre-fetch BS in background so it's ready when the user needs it
    _prefetch_bs_background(company, year)
    # Pre-fetch previous year P&L in background for trailing 12M
    _prefetch_prev_year_background(company, year)

    return result


def load_pl_section(company: str, year: int, section: str,
                    *, force_refresh: bool = False) -> dict:
    """Compute a specific P&L detail section from cached df_stmt.

    Returns a dict of {key: list[dict]} for the section's tables.
    """
    if company not in VALID_COMPANIES:
        raise ValueError(f"Unknown company: {company!r}")
    if section not in SECTION_REGISTRY:
        raise ValueError(f"Unknown section: {section!r}")

    # Check section result cache
    if not force_refresh:
        cached_sections = _caches["pl_sections"].get(company, year)
        if cached_sections and section in cached_sections:
            logger.info("Serving cached section '%s' for %s/%d", section, company, year)
            return cached_sections[section]

    t0 = time.perf_counter()

    # Get df_stmt + preagg (from memory, disk, or SQL)
    df_stmt, preagg = _ensure_pl_stmt_cached(company, year, force_refresh=force_refresh)

    # Compute the section
    section_dfs = compute_pl_section(df_stmt, preagg, section)
    section_records = {key: _df_to_records(df) for key, df in section_dfs.items()}

    # Cache the section result (accumulate into existing dict)
    cached_sections = _caches["pl_sections"].get(company, year) or {}
    cached_sections[section] = section_records
    _caches["pl_sections"].set(company, year, cached_sections)

    logger.info("Computed section '%s' for %s/%d: %.2fs", section, company, year, time.perf_counter() - t0)
    return section_records


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


def _prefetch_prev_year_background(company: str, year: int) -> None:
    """Pre-fetch previous-year P&L df_stmt so trailing 12M is fast.

    Checks disk cache first (sub-second), falls back to SQL if needed.
    """
    prev_year = year - 1
    if prev_year < MIN_YEAR:
        return
    key = ("prev_pl", company, prev_year)
    with _bg_lock:
        if _caches["pl_stmt"].get(company, prev_year) is not None:
            return
        existing = _bg_tasks.get(key)
        if existing is not None and existing.is_alive():
            return

        def worker():
            try:
                _ensure_pl_stmt_cached(company, prev_year)
                logger.info("Background prev-year pre-fetch done for %s/%d", company, prev_year)
            except Exception:
                logger.exception("Background prev-year pre-fetch failed for %s/%d", company, prev_year)
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
    ic_filter: str = "all",
) -> list[dict]:
    """Return raw journal entries matching the given partida + optional month/filter.

    If month is None, returns records for all months (full period).
    If the data hasn't been loaded yet, triggers a load first.
    Checks P&L data first; if no match, falls back to BS data.

    ic_filter: "all" (default), "ex_ic" (exclude intercompany),
               "only_ic" (only intercompany rows).
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

    # Apply intercompany filter
    if ic_filter == "ex_ic" and IS_INTERCOMPANY in df.columns:
        mask = mask & (~df[IS_INTERCOMPANY])
    elif ic_filter == "only_ic" and IS_INTERCOMPANY in df.columns:
        mask = mask & (df[IS_INTERCOMPANY])

    result = df.loc[mask, _DETAIL_COLUMNS].copy()
    result[FECHA] = result[FECHA].dt.strftime("%Y-%m-%d")
    result = result.sort_values(SALDO, ascending=False).reset_index(drop=True)
    return _df_to_records(result)
