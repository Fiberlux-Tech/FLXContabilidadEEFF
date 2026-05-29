"""Data service — fetches P&L + BS from SQL views, returns JSON-ready dicts.

Sole data path for the web API: serves report data from an in-memory cache,
fetching small aggregated results from the SQL views on a miss.

Split endpoints (load_pl_data / load_bs_data) allow the dashboard to fetch
P&L first (fast) and defer BS until the user needs it.

Detail P&L sections (ingresos, costo, etc.) are computed lazily via
load_pl_section() — only when the user navigates to that view.
"""

import logging
import time
import threading
from collections import OrderedDict

import numpy as np
import pandas as pd
import psutil

from data.fetcher import (
    fetch_pnl_summary_only, fetch_bs_summary_only,
    fetch_pnl_preagg_only,
    fetch_bs_detalle_cuenta_only, fetch_bs_detalle_nit_only,
    fetch_bs_last_month_only,
    fetch_pnl_detail_only, fetch_pnl_detail_count_only,
    fetch_bs_detail_only, fetch_bs_detail_count_only,
)
from accounting.aggregation import (
    ensure_month_columns, sales_details,
    proyectos_especiales,
    detail_by_ceco, detail_by_cuenta, detail_ceco_by_cuenta,
    detail_resultado_financiero, detail_diferencia_cambio, detail_planilla,
    detail_proveedores_by_ceco, ALLOWED_PROVEEDORES_CECOS,
    bs_detail_by_cuenta, bs_top20_by_nit, append_total_row,
)
from accounting.statements import pl_summary_from_view, bs_summary_from_view
from accounting.notes import BS_DETAIL_ENTRIES
from config.calendar import MONTH_NAMES, MONTH_NAMES_LIST, MIN_YEAR
from config.company import VALID_COMPANIES
from config.views import statement_for_view
from config.fields import (
    ASIENTO, CUENTA_CONTABLE, DESCRIPCION, NIT, RAZON_SOCIAL,
    CENTRO_COSTO, DESC_CECO, FECHA, SALDO, PARTIDA_PL, MES,
)

logger = logging.getLogger("flxcontabilidad.data_service")


# ── In-memory LRU+TTL cache ──────────────────────────────────────────────

class LRUTTLCache:
    """Thread-safe LRU cache with per-entry TTL expiration.

    Keyed by (company, year) tuples. Each entry holds transformed data + timestamp.
    """

    def __init__(self, name: str, ttl: int = 10800, max_entries: int = 20):
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


# ── Single-flight: deduplicate concurrent fetches ─────────────────────
#
# When the in-memory cache misses, multiple threads landing on the same
# (company, year, kind) must not all fire the same SQL query.
# A per-key lock serializes them: the first thread fetches and populates
# the cache; later threads re-check the cache under the lock and return
# the just-fetched data without a second DB hit.
#
# `force_refresh=True` callers (explicit user "refresh" action) bypass this
# coalescing — they intentionally want a fresh fetch.

_inflight_locks: dict[tuple[str, int, str], threading.Lock] = {}
_inflight_lock_guard = threading.Lock()


def _get_inflight_lock(company: str, year: int, kind: str) -> threading.Lock:
    """Return (creating if missing) the single-flight lock for a fetch key."""
    key = (company, year, kind)
    with _inflight_lock_guard:
        lock = _inflight_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _inflight_locks[key] = lock
        return lock


# All buckets hold small aggregated SQL results (summaries, sections, the
# preagg triple) and keep the constructor default max_entries=20 from
# LRUTTLCache.__init__ — no full row-level DataFrames are cached anymore.
_caches: dict[str, LRUTTLCache] = {
    "result": LRUTTLCache("result"),
    "pl_result": LRUTTLCache("pl_result"),
    "bs_result": LRUTTLCache("bs_result"),
    "pl_df": LRUTTLCache("pl_df"),
    "pl_sections": LRUTTLCache("pl_sections"),
    # Phase F: the (preagg, ex_ic, only_ic) triple sliced from VISTA_PNL_PREAGG.
    # ~10²–10³ rows per frame — small enough to keep the default max_entries.
    "pl_preagg_triple": LRUTTLCache("pl_preagg_triple"),
}


def get_cache_stats() -> dict:
    """Return cache hit/miss counters and current entry counts per store."""
    return {name: cache.stats() for name, cache in _caches.items()}


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

    Vectorized via pd.merge on a stringified composite key. Preserves
    reference row order (left merge) and reference column order.
    """
    if filtered.empty or reference.empty:
        result = reference.copy()
        for col in result.select_dtypes(include="number").columns:
            result[col] = 0
        return result

    num_cols = list(reference.select_dtypes(include="number").columns)
    label_cols = [c for c in reference.columns if c not in num_cols]

    if not label_cols:
        result = reference.copy()
        for col in num_cols:
            result[col] = 0.0
        return result

    _KEY = "__reindex_key__"
    # .astype(str) normalizes category vs object dtype mismatches (e.g. CENTRO_COSTO).
    ref_keys = reference[label_cols].astype(str).agg("|".join, axis=1)
    filt_keys = filtered[label_cols].astype(str).agg("|".join, axis=1)

    # Preserve a latent quirk of the prior implementation: when *filtered*
    # contained duplicate label-keys, dict(zip(...)) kept only the LAST
    # occurrence. Reproduce exactly via drop_duplicates(keep="last").
    # Do not "fix" this here — this change is purely a perf rewrite.
    filt_numeric = filtered[num_cols].copy()
    filt_numeric[_KEY] = filt_keys.values
    filt_numeric = filt_numeric.drop_duplicates(subset=[_KEY], keep="last")

    # Left-merge from reference preserves reference row order exactly.
    left = pd.DataFrame({_KEY: ref_keys.values})
    merged = left.merge(filt_numeric, on=_KEY, how="left")

    result = reference.copy()
    for col in num_cols:
        result[col] = merged[col].fillna(0.0).to_numpy()

    return result


def _add_ic_variants(base: dict[str, pd.DataFrame],
                     preagg_ex_ic: pd.DataFrame,
                     preagg_only_ic: pd.DataFrame,
                     compute_fn) -> dict[str, pd.DataFrame]:
    """Run *compute_fn* on the IC-filtered preaggs and merge results with *base*.

    For each key in *base*, adds key_ex_ic and key_only_ic variants
    reindexed to match the original row structure.

    Phase F: the three preagg frames come pre-split from VISTA_PNL_PREAGG (each
    carries the matching SALDO_* column as SALDO and the full label grain
    including NIT/RAZON_SOCIAL), so each frame serves as both the `df` and the
    `preagg` argument to *compute_fn* — the NIT-grain functions read `df`, the
    rest read `preagg`, and both see the same correctly-summed rows.  There is
    no longer a row-level df_stmt to re-filter by IS_INTERCOMPANY.
    """
    ex_ic_dfs = compute_fn(preagg_ex_ic, preagg_ex_ic)
    only_ic_dfs = compute_fn(preagg_only_ic, preagg_only_ic)

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


def _compute_ingresos(df_stmt, preagg, preagg_ex_ic, preagg_only_ic):
    base = _compute_ingresos_base(df_stmt, preagg)
    return _add_ic_variants(base, preagg_ex_ic, preagg_only_ic,
                            _compute_ingresos_base)


def _compute_costo_base(df_stmt, preagg):
    return {
        "costo": detail_by_ceco(df_stmt, ["COSTO"], ascending=True, with_total_row=True, preagg=preagg),
        "costo_by_cuenta": detail_ceco_by_cuenta(df_stmt, ["COSTO"], preagg=preagg),
    }


def _compute_costo(df_stmt, preagg, preagg_ex_ic, preagg_only_ic):
    base = _compute_costo_base(df_stmt, preagg)
    return _add_ic_variants(base, preagg_ex_ic, preagg_only_ic,
                            _compute_costo_base)


def _compute_gasto_venta_base(df_stmt, preagg):
    return {
        "gasto_venta": detail_by_ceco(df_stmt, ["GASTO VENTA"], ascending=True, with_total_row=True, preagg=preagg),
        "gasto_venta_by_cuenta": detail_ceco_by_cuenta(df_stmt, ["GASTO VENTA"], preagg=preagg),
    }


def _compute_gasto_venta(df_stmt, preagg, preagg_ex_ic, preagg_only_ic):
    base = _compute_gasto_venta_base(df_stmt, preagg)
    return _add_ic_variants(base, preagg_ex_ic, preagg_only_ic,
                            _compute_gasto_venta_base)


def _compute_gasto_admin_base(df_stmt, preagg):
    return {
        "gasto_admin": detail_by_ceco(df_stmt, ["GASTO ADMIN"], ascending=True, with_total_row=True, preagg=preagg),
        "gasto_admin_by_cuenta": detail_ceco_by_cuenta(df_stmt, ["GASTO ADMIN"], preagg=preagg),
    }


def _compute_gasto_admin(df_stmt, preagg, preagg_ex_ic, preagg_only_ic):
    base = _compute_gasto_admin_base(df_stmt, preagg)
    return _add_ic_variants(base, preagg_ex_ic, preagg_only_ic,
                            _compute_gasto_admin_base)


def _compute_otros_egresos_base(df_stmt, preagg):
    return {
        "otros_ingresos": detail_by_cuenta(df_stmt, ["OTROS INGRESOS"], with_total_row=True, preagg=preagg),
        "otros_ingresos_by_cuenta": detail_ceco_by_cuenta(df_stmt, ["OTROS INGRESOS"], preagg=preagg),
        "otros_egresos": detail_by_cuenta(df_stmt, ["OTROS EGRESOS"], ascending=True, with_total_row=True, preagg=preagg),
        "otros_egresos_by_cuenta": detail_ceco_by_cuenta(df_stmt, ["OTROS EGRESOS"], preagg=preagg),
        "participacion_by_cuenta": detail_ceco_by_cuenta(df_stmt, ["PARTICIPACION DE TRABAJADORES"], preagg=preagg),
        "provision_by_cuenta": detail_ceco_by_cuenta(df_stmt, ["PROVISION INCOBRABLE"], preagg=preagg),
    }


def _compute_otros_egresos(df_stmt, preagg, preagg_ex_ic, preagg_only_ic):
    base = _compute_otros_egresos_base(df_stmt, preagg)
    return _add_ic_variants(base, preagg_ex_ic, preagg_only_ic,
                            _compute_otros_egresos_base)


def _compute_dya_base(df_stmt, preagg):
    return {
        "dya_costo": detail_by_ceco(df_stmt, ["D&A - COSTO"], ascending=True, with_total_row=True, preagg=preagg),
        "dya_costo_by_cuenta": detail_ceco_by_cuenta(df_stmt, ["D&A - COSTO"], preagg=preagg),
        "dya_gasto": detail_by_ceco(df_stmt, ["D&A - GASTO"], ascending=True, with_total_row=True, preagg=preagg),
        "dya_gasto_by_cuenta": detail_ceco_by_cuenta(df_stmt, ["D&A - GASTO"], preagg=preagg),
    }


def _compute_dya(df_stmt, preagg, preagg_ex_ic, preagg_only_ic):
    base = _compute_dya_base(df_stmt, preagg)
    return _add_ic_variants(base, preagg_ex_ic, preagg_only_ic,
                            _compute_dya_base)


def _compute_resultado_financiero_base(df_stmt, preagg):
    res = detail_resultado_financiero(df_stmt, preagg=preagg)
    return {
        "resultado_financiero_ingresos": res.ingresos,
        "resultado_financiero_gastos": res.gastos,
    }


def _compute_resultado_financiero(df_stmt, preagg, preagg_ex_ic, preagg_only_ic):
    base = _compute_resultado_financiero_base(df_stmt, preagg)
    return _add_ic_variants(base, preagg_ex_ic, preagg_only_ic,
                            _compute_resultado_financiero_base)


def _compute_diferencia_cambio_base(df_stmt, preagg):
    res = detail_diferencia_cambio(df_stmt, preagg=preagg)
    return {
        "diferencia_cambio_ingresos": res.ingresos,
        "diferencia_cambio_gastos": res.gastos,
    }


def _compute_diferencia_cambio(df_stmt, preagg, preagg_ex_ic, preagg_only_ic):
    base = _compute_diferencia_cambio_base(df_stmt, preagg)
    return _add_ic_variants(base, preagg_ex_ic, preagg_only_ic,
                            _compute_diferencia_cambio_base)


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


def _compute_analysis_pl_finanzas(df_stmt, preagg, preagg_ex_ic, preagg_only_ic):
    base = _compute_analysis_pl_finanzas_base(df_stmt, preagg)
    return _add_ic_variants(base, preagg_ex_ic, preagg_only_ic,
                            _compute_analysis_pl_finanzas_base)


def _compute_analysis_planilla_base(df_stmt, preagg):
    return {
        "planilla_by_cuenta": detail_planilla(df_stmt, preagg=preagg),
        "revenue_by_cuenta": sales_details(df_stmt, preagg=preagg),
        "otros_revenue_by_cuenta": detail_by_cuenta(df_stmt, ["OTROS INGRESOS"], preagg=preagg),
    }


def _compute_analysis_planilla(df_stmt, preagg, preagg_ex_ic, preagg_only_ic):
    base = _compute_analysis_planilla_base(df_stmt, preagg)
    return _add_ic_variants(base, preagg_ex_ic, preagg_only_ic,
                            _compute_analysis_planilla_base)


def _compute_analysis_proveedores(df_stmt, preagg, *, ceco: str = "100.113.01"):
    from config.fields import CENTRO_COSTO, DESC_CECO
    # Build list of available CECOs with their descriptions from the data
    ceco_labels = []
    for code in ALLOWED_PROVEEDORES_CECOS:
        rows = df_stmt[df_stmt[CENTRO_COSTO] == code]
        if rows.empty:
            continue
        desc = rows[DESC_CECO].dropna().unique()
        label = str(desc[0]) if len(desc) > 0 else code
        ceco_labels.append({"ceco": code, "label": label})
    return {
        "proveedores_transporte": detail_proveedores_by_ceco(df_stmt, ceco),
        "proveedores_cecos": pd.DataFrame(ceco_labels),
    }


def _compute_analysis_flujo_caja_base(df_stmt, preagg):
    return {
        "flujo_ingresos_ord_by_cuenta": detail_by_cuenta(df_stmt, ["INGRESOS ORDINARIOS"], preagg=preagg),
        "flujo_ingresos_proy_by_cuenta": detail_by_cuenta(df_stmt, ["INGRESOS PROYECTOS"], preagg=preagg),
        "flujo_costo_by_cuenta": detail_ceco_by_cuenta(df_stmt, ["COSTO"], preagg=preagg),
        "flujo_gasto_venta_by_cuenta": detail_ceco_by_cuenta(df_stmt, ["GASTO VENTA"], preagg=preagg),
        "flujo_gasto_admin_by_cuenta": detail_ceco_by_cuenta(df_stmt, ["GASTO ADMIN"], preagg=preagg),
        "flujo_participacion_by_cuenta": detail_ceco_by_cuenta(df_stmt, ["PARTICIPACION DE TRABAJADORES"], preagg=preagg),
        "flujo_otros_ingresos_by_cuenta": detail_ceco_by_cuenta(df_stmt, ["OTROS INGRESOS"], preagg=preagg),
        "flujo_otros_egresos_by_cuenta": detail_ceco_by_cuenta(df_stmt, ["OTROS EGRESOS"], preagg=preagg),
    }


def _compute_analysis_flujo_caja(df_stmt, preagg, preagg_ex_ic, preagg_only_ic):
    base = _compute_analysis_flujo_caja_base(df_stmt, preagg)
    return _add_ic_variants(base, preagg_ex_ic, preagg_only_ic,
                            _compute_analysis_flujo_caja_base)


SECTION_REGISTRY: dict[str, callable] = {
    "ingresos": _compute_ingresos,
    "costo": _compute_costo,
    "gasto_venta": _compute_gasto_venta,
    "gasto_admin": _compute_gasto_admin,
    "otros_egresos": _compute_otros_egresos,
    "dya": _compute_dya,
    "resultado_financiero": _compute_resultado_financiero,
    "diferencia_cambio": _compute_diferencia_cambio,
    "analysis_pl_finanzas": _compute_analysis_pl_finanzas,
    "analysis_planilla": _compute_analysis_planilla,
    "analysis_proveedores": _compute_analysis_proveedores,
    "analysis_flujo_caja": _compute_analysis_flujo_caja,
}

VALID_PL_SECTIONS = frozenset(SECTION_REGISTRY.keys())


def compute_pl_section(df_stmt: pd.DataFrame, preagg: pd.DataFrame,
                       preagg_ex_ic: pd.DataFrame, preagg_only_ic: pd.DataFrame,
                       section_name: str, **kwargs) -> dict[str, pd.DataFrame]:
    """Compute a specific P&L detail section from prepared data.

    Returns {key: DataFrame} for the section's tables.
    Extra kwargs are forwarded only to sections that accept them (e.g. analysis_proveedores).
    """
    compute_fn = SECTION_REGISTRY[section_name]
    # analysis_proveedores does not call _add_ic_variants — special-case by name
    # so it keeps its (df_stmt, preagg, **kwargs) signature unchanged.
    if section_name == "analysis_proveedores":
        if kwargs:
            return compute_fn(df_stmt, preagg, **kwargs)
        return compute_fn(df_stmt, preagg)
    if kwargs:
        return compute_fn(df_stmt, preagg, preagg_ex_ic, preagg_only_ic, **kwargs)
    return compute_fn(df_stmt, preagg, preagg_ex_ic, preagg_only_ic)


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


# ── Phase F: VISTA_PNL_PREAGG → (preagg, ex_ic, only_ic) triple ───────────
#
# The view returns one long row per (MES, PARTIDA_PL, CECO, CUENTA, NIT) with
# three SALDO columns.  Each detail-section variant is the SAME label grain
# with SALDO drawn from the matching SALDO_* column, so we slice the fetched
# frame into three frames that are drop-in replacements for the old
# preaggregate(df_stmt) / preaggregate(df_stmt[ic]) frames.
#
# Column contract must match accounting.aggregation.preaggregate exactly:
#   [PARTIDA_PL, CENTRO_COSTO, DESC_CECO, CUENTA_CONTABLE, DESCRIPCION, MES, SALDO]
# plus NIT / RAZON_SOCIAL (carried so proyectos_especiales /
# detail_proveedores_by_ceco, which read the frame as their `df` arg, find
# the columns they need).  PARTIDA_PL / CENTRO_COSTO are cast to category to
# match prepare_pnl_from_view's dtypes, so observed=True grouping and sort
# order are identical to the pre-Phase-F path.

_PREAGG_LABEL_COLS = [
    PARTIDA_PL, CENTRO_COSTO, DESC_CECO, CUENTA_CONTABLE, DESCRIPCION,
    NIT, RAZON_SOCIAL, MES,
]
_PREAGG_SALDO_SOURCE = {
    "total": "SALDO_TOTAL",
    "ex_ic": "SALDO_EX_IC",
    "only_ic": "SALDO_ONLY_IC",
}


def _preagg_variant(raw: pd.DataFrame, saldo_col: str) -> pd.DataFrame:
    """Slice the fetched VISTA_PNL_PREAGG frame to one IC variant.

    Takes *saldo_col* (SALDO_TOTAL / SALDO_EX_IC / SALDO_ONLY_IC) as SALDO and
    drops rows that are NULL for that variant (the view emits NULL when a
    (grain, variant) had no contributing rows — e.g. an ex_ic SUM over a row
    set that was entirely intercompany).  Dropping them matches the old path,
    where preaggregate(df_stmt[~ic]) simply had no such rows.
    """
    if raw.empty:
        return pd.DataFrame(columns=[*_PREAGG_LABEL_COLS, SALDO])
    out = raw[[*_PREAGG_LABEL_COLS, saldo_col]].copy()
    out = out[out[saldo_col].notna()]
    out = out.rename(columns={saldo_col: SALDO})
    out[PARTIDA_PL] = out[PARTIDA_PL].astype("category")
    out[CENTRO_COSTO] = out[CENTRO_COSTO].astype("category")
    return out.reset_index(drop=True)


def _split_pnl_preagg(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Build the (preagg, preagg_ex_ic, preagg_only_ic) triple from one fetch."""
    return (
        _preagg_variant(raw, _PREAGG_SALDO_SOURCE["total"]),
        _preagg_variant(raw, _PREAGG_SALDO_SOURCE["ex_ic"]),
        _preagg_variant(raw, _PREAGG_SALDO_SOURCE["only_ic"]),
    )


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

    # P&L transforms — summaries + all detail sections, all from SQL views
    # (VISTA_PNL_SUMARIO + VISTA_PNL_PREAGG).  No row-level df_stmt.
    pl, pl_records = _run_pl_transforms(company, year)

    # BS summary from VISTA_BS_SUMARIO (Phase C).  Empty-check via a cheap
    # summary fetch — the row-level df_bs is no longer built here.  BS note
    # tables are produced by load_bs_data, not this path.
    bs_long = fetch_bs_summary_only(company, year)
    if not bs_long.empty:
        bs = bs_summary_from_view(bs_long, pl_summary_df=pl)
    else:
        bs = pd.DataFrame()

    logger.info("Transforms: %.2fs", time.perf_counter() - t0)

    result = {
        **pl_records,
        "bs_summary": _df_to_records(bs),
        "company": company,
        "year": year,
        "months": MONTH_NAMES_LIST,
    }

    _caches["result"].set(company, year, result)
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

def _run_pl_transforms(company: str, year: int) -> tuple[pd.DataFrame, dict]:
    """Full P&L transform pipeline: summaries + all detail sections.

    Returns (pl_df, all_records_dict).
    Used by load_report_data (the /api/data/load "everything at once" path).

    Phase F: summaries come from VISTA_PNL_SUMARIO and detail sections from
    VISTA_PNL_PREAGG — no row-level df_stmt is built or grouped.
    """
    summaries = pl_summary_from_view(fetch_pnl_summary_only(company, year))
    pl         = ensure_month_columns(summaries["total"])
    pl_ex_ic   = ensure_month_columns(summaries["ex_ic"])
    pl_only_ic = ensure_month_columns(summaries["only_ic"])
    records = {
        "pl_summary": _df_to_records(pl),
        "pl_summary_ex_ic": _df_to_records(pl_ex_ic),
        "pl_summary_only_ic": _df_to_records(pl_only_ic),
    }

    preagg, preagg_ex_ic, preagg_only_ic = _ensure_pl_preagg_cached(company, year)

    # Compute all detail sections.  The base preagg doubles as the `df` arg
    # (carries NIT/RAZON_SOCIAL for the NIT-grain sections).
    for section_name in SECTION_REGISTRY:
        section_dfs = compute_pl_section(preagg, preagg,
                                         preagg_ex_ic, preagg_only_ic,
                                         section_name)
        for key, df in section_dfs.items():
            if key not in records:  # avoid duplicating keys across sections
                records[key] = _df_to_records(df)

    return pl, records


def _ensure_pl_preagg_cached(company: str, year: int, *, force_refresh: bool = False
                             ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return (preagg, preagg_ex_ic, preagg_only_ic) for a company/year.

    The three frames are sliced from a single VISTA_PNL_PREAGG fetch instead of
    grouped from a cached ~400 MB row-level df_stmt.  No disk pickle, no
    df_stmt — just a small SQL result cached in-memory.

    Concurrent calls for the same (company, year) coalesce on the in-process
    single-flight lock (same ("pl") key used by the summary path); force_refresh
    callers bypass coalescing.
    """
    if not force_refresh:
        hit = _caches["pl_preagg_triple"].get(company, year)
        if hit is not None:
            return hit

    lock = _get_inflight_lock(company, year, "pl")
    with lock:
        if not force_refresh:
            hit = _caches["pl_preagg_triple"].get(company, year)
            if hit is not None:
                logger.info("P&L preagg %s/%d: served from cache after lock wait", company, year)
                return hit

        t0 = time.perf_counter()
        raw = fetch_pnl_preagg_only(company, year)
        logger.info("P&L preagg fetch: %.2fs (%d rows)", time.perf_counter() - t0, len(raw))

        triple = _split_pnl_preagg(raw)
        _caches["pl_preagg_triple"].set(company, year, triple)
        return triple


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
        _caches["pl_sections"].pop(company, year)
        _caches["pl_preagg_triple"].pop(company, year)

    # Compute summaries from VISTA_PNL_SUMARIO — one SQL roundtrip returns all
    # three IC variants.  Detail sections fetch VISTA_PNL_PREAGG lazily via
    # load_pl_section → _ensure_pl_preagg_cached; the summary path no longer
    # needs to build or cache a row-level df_stmt.
    summaries = pl_summary_from_view(fetch_pnl_summary_only(company, year))
    pl         = ensure_month_columns(summaries["total"])
    pl_ex_ic   = ensure_month_columns(summaries["ex_ic"])
    pl_only_ic = ensure_month_columns(summaries["only_ic"])

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
    # Pre-compute the most-clicked P&L sections so navigation feels instant
    _prefetch_pl_sections_background(company, year)

    return result


def load_pl_section(company: str, year: int, section: str,
                    *, force_refresh: bool = False, **kwargs) -> dict:
    """Compute a specific P&L detail section from cached df_stmt.

    Returns a dict of {key: list[dict]} for the section's tables.
    Extra kwargs (e.g. ceco) are forwarded to the section's compute function.
    """
    if company not in VALID_COMPANIES:
        raise ValueError(f"Unknown company: {company!r}")
    if section not in SECTION_REGISTRY:
        raise ValueError(f"Unknown section: {section!r}")

    # Cache key includes extra params so different ceco values are cached separately
    cache_key = section if not kwargs else f"{section}:{','.join(f'{k}={v}' for k, v in sorted(kwargs.items()))}"

    # Check section result cache
    if not force_refresh:
        cached_sections = _caches["pl_sections"].get(company, year)
        if cached_sections and cache_key in cached_sections:
            logger.info("Serving cached section '%s' for %s/%d", cache_key, company, year)
            return cached_sections[cache_key]

    t0 = time.perf_counter()

    # Get the preagg triple (sliced from one VISTA_PNL_PREAGG fetch, cached).
    preagg, preagg_ex_ic, preagg_only_ic = _ensure_pl_preagg_cached(
        company, year, force_refresh=force_refresh)

    # Compute the section.  The base preagg frame doubles as the `df` argument:
    # it carries NIT/RAZON_SOCIAL for the NIT-grain sections and is the same
    # grain the preagg-reading sections expect.
    section_dfs = compute_pl_section(
        preagg, preagg, preagg_ex_ic, preagg_only_ic, section, **kwargs)
    section_records = {key: _df_to_records(df) for key, df in section_dfs.items()}

    # Cache the section result (accumulate into existing dict)
    cached_sections = _caches["pl_sections"].get(company, year) or {}
    cached_sections[cache_key] = section_records
    _caches["pl_sections"].set(company, year, cached_sections)

    logger.info("Computed section '%s' for %s/%d: %.2fs", cache_key, company, year, time.perf_counter() - t0)
    return section_records


def _try_bs_result_from_cache(company: str, year: int) -> dict | None:
    """Return cached BS result dict if available, promoting from the full
    `result` cache when needed. Pure read with one cache-promotion side effect."""
    cached = _caches["bs_result"].get(company, year)
    if cached:
        logger.info("Serving cached BS data for %s/%d", company, year)
        return cached
    full = _caches["result"].get(company, year)
    if full and "bs_efectivo" in full:
        logger.info("Serving BS from full cache for %s/%d", company, year)
        bs_result = {k: v for k, v in full.items()
                     if k == "bs_summary" or k.startswith("bs_") or k in ("company", "year", "months")}
        _caches["bs_result"].set(company, year, bs_result)
        return bs_result
    return None


def load_bs_data(company: str, year: int, *, force_refresh: bool = False) -> dict:
    """Fetch and transform BS data.  Requires P&L to have been loaded first
    (for UTILIDAD NETA injection into PATRIMONIO).

    If P&L is not cached, loads it first as a safety net.

    Concurrent calls for the same (company, year) coalesce on a single-flight
    lock so only one thread fires the BS DB query.
    """
    if company not in VALID_COMPANIES:
        raise ValueError(f"Unknown company: {company!r}")

    if not force_refresh:
        hit = _try_bs_result_from_cache(company, year)
        if hit is not None:
            return hit

    # Slow path: serialize concurrent fetchers of the same (company, year)
    # within this worker. Post-Phase-F the BS fetch is a handful of small
    # SQL-view reads (no row-level df_bs), so cross-worker dedup isn't worth a
    # flock — at worst each of the 2 workers fires the same cheap query once on
    # a simultaneous cold miss. The in-process lock still coalesces the threads
    # within a worker that actually contend.
    lock = _get_inflight_lock(company, year, "bs")
    with lock:
        if not force_refresh:
            hit = _try_bs_result_from_cache(company, year)
            if hit is not None:
                logger.info("BS %s/%d: served from cache after lock wait", company, year)
                return hit

        t0 = time.perf_counter()

        # Ensure P&L summary is available (needed for Resultados del Ejercicio).
        # load_pl_data has its own single-flight lock on ("pl"), distinct from
        # ours on ("bs"), so this nested call cannot self-deadlock.
        pl_df = _caches["pl_df"].get(company, year)
        if pl_df is None:
            logger.info("P&L not cached for %s/%d — loading first (BS dependency)", company, year)
            load_pl_data(company, year)
            pl_df = _caches["pl_df"].get(company, year)

        t1 = time.perf_counter()
        # BS summary from VISTA_BS_SUMARIO (Phase C).  last_month = last
        # posted BS month (MAX(MES) over the row-level view); None ⇒ no BS
        # activity for the year ⇒ empty result, no notes.
        last_month = fetch_bs_last_month_only(company, year)
        if last_month is not None:
            bs_long = fetch_bs_summary_only(company, year)
            bs = bs_summary_from_view(bs_long, pl_summary_df=pl_df)
        else:
            bs = pd.DataFrame()
        logger.info("BS transforms: %.2fs", time.perf_counter() - t1)

        result = {
            "bs_summary": _df_to_records(bs),
            "company": company,
            "year": year,
            "months": MONTH_NAMES_LIST,
        }

        # BS note detail tables — built from pre-aggregated cumsum views
        # (Phase F).  No row-level df_bs; cumsum + densification done in SQL.
        if last_month is not None:
            for key, partidas, include_pf, exclude_pf in BS_DETAIL_ENTRIES:
                frame = fetch_bs_detalle_cuenta_only(company, year, partidas)
                detail = bs_detail_by_cuenta(
                    frame,
                    last_month=last_month,
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
                frame = fetch_bs_detalle_nit_only(company, year, partidas)
                result[key] = _df_to_records(bs_top20_by_nit(frame, last_month=last_month))

        _caches["bs_result"].set(company, year, result)
        logger.info("Total load_bs_data: %.2fs", time.perf_counter() - t0)

        return result


# ── Background BS pre-fetch ───────────────────────────────────────────

_bg_lock = threading.Lock()
_bg_tasks: dict[tuple[str, int], threading.Thread] = {}

# OOM safety valve: skip speculative prefetches when free RAM is below this.
# Post-Phase-F the prefetches only pull small SQL-view results, so this is now
# cheap insurance rather than the load-bearing guard it was when a cold click
# fanned out three prefetches that each cached a ~400 MB row-level DataFrame and
# once SIGKILLed a worker. The box is still memory-bound (5.8 GB), so the valve
# stays.
_PREFETCH_MIN_AVAILABLE_BYTES = 800 * 1024 * 1024


def _memory_ok_for_prefetch(prefetch_name: str) -> bool:
    """Return True if there's enough free RAM to safely spawn a prefetch.

    Cheap synchronous read of system available memory. mem_monitor only logs
    this periodically; it does not expose a live value, so we sample psutil
    directly at gate time. Fails open — a sampling error must not silently
    disable the warm-cache behavior the dashboard relies on.
    """
    try:
        available = psutil.virtual_memory().available
    except Exception:
        logger.exception("memory gate sample failed; allowing %s", prefetch_name)
        return True
    if available < _PREFETCH_MIN_AVAILABLE_BYTES:
        logger.warning(
            "Skipping %s: available memory %.0f MB below %.0f MB threshold",
            prefetch_name,
            available / (1024 * 1024),
            _PREFETCH_MIN_AVAILABLE_BYTES / (1024 * 1024),
        )
        return False
    return True


def _prefetch_bs_background(company: str, year: int) -> None:
    """Spawn a daemon thread to pre-fetch BS data so it's cached when needed."""
    if not _memory_ok_for_prefetch("BS prefetch"):
        return
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
    """Pre-fetch previous-year P&L preagg so trailing-12M section nav is fast.

    Warms the prev-year VISTA_PNL_PREAGG triple — a small SQL result, not a
    row-level df_stmt.  Trailing-12M summary rows come from VISTA_PNL_SUMARIO
    on demand; drill-down crosses the year boundary via the Phase D path.
    """
    if not _memory_ok_for_prefetch("prev-year prefetch"):
        return
    prev_year = year - 1
    if prev_year < MIN_YEAR:
        return
    key = ("prev_pl", company, prev_year)
    with _bg_lock:
        if _caches["pl_preagg_triple"].get(company, prev_year) is not None:
            return
        existing = _bg_tasks.get(key)
        if existing is not None and existing.is_alive():
            return

        def worker():
            try:
                _ensure_pl_preagg_cached(company, prev_year)
                logger.info("Background prev-year pre-fetch done for %s/%d", company, prev_year)
            except Exception:
                logger.exception("Background prev-year pre-fetch failed for %s/%d", company, prev_year)
            finally:
                with _bg_lock:
                    _bg_tasks.pop(key, None)

        t = threading.Thread(target=worker, daemon=True)
        _bg_tasks[key] = t
        t.start()


# Hardcoded based on canonical P&L workflow: ingresos → costo → gasto_admin
# are the universal first-clicked sections. No usage analytics in the codebase
# to drive this dynamically. Excludes analysis_proveedores (requires a ceco
# kwarg) and the heavier analysis_* sections (rarely first-clicked).
PREFETCH_PL_SECTIONS = ("ingresos", "costo", "gasto_admin")

_bg_pl_section_tasks: dict[tuple[str, int], threading.Thread] = {}


def _prefetch_pl_sections_background(company: str, year: int) -> None:
    """Pre-compute the most-clicked P&L sections in one daemon thread."""
    if not _memory_ok_for_prefetch("P&L section prefetch"):
        return
    key = (company, year)
    with _bg_lock:
        cached = _caches["pl_sections"].get(company, year) or {}
        if all(s in cached for s in PREFETCH_PL_SECTIONS):
            return
        existing = _bg_pl_section_tasks.get(key)
        if existing is not None and existing.is_alive():
            return

        def worker():
            try:
                for section in PREFETCH_PL_SECTIONS:
                    # NO force_refresh — caller already invalidated, we just
                    # populate the freshly-empty cache.
                    load_pl_section(company, year, section)
                logger.info(
                    "Background P&L section pre-fetch done for %s/%d (%s)",
                    company, year, ",".join(PREFETCH_PL_SECTIONS),
                )
            except Exception:
                logger.exception(
                    "Background P&L section pre-fetch failed for %s/%d",
                    company, year,
                )
            finally:
                with _bg_lock:
                    _bg_pl_section_tasks.pop(key, None)

        t = threading.Thread(target=worker, daemon=True)
        _bg_pl_section_tasks[key] = t
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
    company: str, view_id: str, partida: str,
    year_month_pairs: list[tuple[int, int]],
    *, offset: int = 0, limit: int = 500,
    filter_col: str | None = None, filter_val: str | None = None,
    ic_filter: str = "all",
) -> tuple[list[dict], int]:
    """Paginated journal-entry drill-down for a single (view, partida) cell.

    Routes to VISTA_PNL_PREPARADO or VISTA_BS_PREPARADO via statement_for_view
    (Phase D, 2026-05-27).  No longer touches in-memory row-level caches;
    each call hits SQL Server with parameterized WHERE + OFFSET/FETCH so the
    summary path and drill-down path no longer share state.

    *year_month_pairs* is a list of (year, MES) tuples — one per period the
    cell spans.  A single-month cell sends one pair; a multi-month cell or
    trailing-12M selection sends N pairs in one query.

    Returns (records, total) where *records* is the current page and
    *total* is COUNT(*) for the same WHERE clause (for "X of Y" UI).
    """
    statement = statement_for_view(view_id)
    if statement == "bs":
        df = fetch_bs_detail_only(
            company, year_month_pairs, partida,
            offset=offset, limit=limit,
            filter_col=filter_col, filter_val=filter_val, ic_filter=ic_filter,
        )
        total = fetch_bs_detail_count_only(
            company, year_month_pairs, partida,
            filter_col=filter_col, filter_val=filter_val, ic_filter=ic_filter,
        )
    else:
        df = fetch_pnl_detail_only(
            company, year_month_pairs, partida,
            offset=offset, limit=limit,
            filter_col=filter_col, filter_val=filter_val, ic_filter=ic_filter,
        )
        total = fetch_pnl_detail_count_only(
            company, year_month_pairs, partida,
            filter_col=filter_col, filter_val=filter_val, ic_filter=ic_filter,
        )

    if not df.empty:
        df[FECHA] = pd.to_datetime(df[FECHA]).dt.strftime("%Y-%m-%d")
    return _df_to_records(df[_DETAIL_COLUMNS]), total
