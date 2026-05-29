import logging
from collections import namedtuple

import pandas as pd

from config.calendar import MONTH_NAMES, MONTH_NAMES_LIST, MONTH_NAMES_SET
from config.fields import (
    CUENTA_CONTABLE, DESCRIPCION, PARTIDA_PL,
    CENTRO_COSTO, DESC_CECO, SALDO, MES, NIT, RAZON_SOCIAL,
)
from config.period import get_period_months, get_ytd_months
from accounting.rules import INGRESO_FINANCIERO_PREFIX


logger = logging.getLogger("plantillas.aggregation")

# Name of the running-total column added by pivot helpers
TOTAL_COL = "TOTAL"

ResultadoFinanciero = namedtuple("ResultadoFinanciero", ["ingresos", "gastos"])


def ensure_month_columns(pivot: pd.DataFrame) -> pd.DataFrame:
    """Reindex a pivot so all 12 month columns exist in JAN–DEC order, fill missing with 0."""
    non_month_cols = [c for c in pivot.columns if c not in MONTH_NAMES_SET]
    return pivot.reindex(columns=non_month_cols + MONTH_NAMES_LIST, fill_value=0)


def pivot_by_month(df: pd.DataFrame, index_cols: list[str] | str, add_total: bool = False) -> pd.DataFrame:
    pivot = pd.pivot_table(
        df, values=SALDO, index=index_cols,
        columns=MES, aggfunc="sum", fill_value=0, observed=True, sort=False,
    )
    pivot.columns = [MONTH_NAMES[int(c)] for c in pivot.columns]
    pivot = pivot.reset_index()
    pivot = ensure_month_columns(pivot)
    if add_total:
        pivot[TOTAL_COL] = pivot[MONTH_NAMES_LIST].sum(axis=1)
    return pivot



def preaggregate(df: pd.DataFrame) -> pd.DataFrame:
    """Pre-aggregate statement data at the finest grain used by detail pivots.

    Groups by (PARTIDA_PL, CENTRO_COSTO, DESC_CECO, CUENTA_CONTABLE,
    DESCRIPCION, MES) summing SALDO once.  Pass the result as *preagg* to
    detail functions to avoid repeated groupby work on the raw DataFrame.
    """
    agg_cols = [PARTIDA_PL, CENTRO_COSTO, DESC_CECO,
                CUENTA_CONTABLE, DESCRIPCION, MES]
    return df.groupby(agg_cols, sort=False, as_index=False, observed=True)[SALDO].sum()


def _detail_pivot(df: pd.DataFrame, partidas: list[str], index_cols: list[str],
                  sort_by: str | list[str] = TOTAL_COL, ascending: bool = False,
                  with_total_row: bool = False, preagg: pd.DataFrame | None = None) -> pd.DataFrame:
    source = preagg if preagg is not None else df
    source = source[source[PARTIDA_PL].isin(partidas)]
    pivot = pivot_by_month(source, index_cols, add_total=True)
    pivot = pivot.sort_values(sort_by, ascending=ascending).reset_index(drop=True)
    if with_total_row:
        pivot = append_total_row(pivot, index_cols[-1])
    return pivot


def append_total_row(pivot: pd.DataFrame, label_col: str) -> pd.DataFrame:
    """Append a TOTAL row summing all numeric columns, with label in label_col."""
    numeric_cols = pivot.select_dtypes(include="number").columns
    totals = pivot[numeric_cols].sum()
    total_row = {c: None for c in pivot.columns}
    total_row[label_col] = TOTAL_COL
    for c in numeric_cols:
        total_row[c] = totals[c]
    return pd.concat([pivot, pd.DataFrame([total_row])], ignore_index=True)


def detail_by_ceco(df: pd.DataFrame, partidas: list[str], ascending: bool = False,
                   with_total_row: bool = False, preagg: pd.DataFrame | None = None) -> pd.DataFrame:
    """Filter to *partidas* and pivot by CENTRO_COSTO + DESC_CECO."""
    return _detail_pivot(df, partidas, [CENTRO_COSTO, DESC_CECO],
                         ascending=ascending, with_total_row=with_total_row, preagg=preagg)


def detail_ceco_by_cuenta(df: pd.DataFrame, partidas: list[str],
                          preagg: pd.DataFrame | None = None) -> pd.DataFrame:
    """Filter to *partidas* and pivot by CECO x CUENTA_CONTABLE (expanded view)."""
    return _detail_pivot(
        df, partidas,
        [CENTRO_COSTO, DESC_CECO, CUENTA_CONTABLE, DESCRIPCION],
        sort_by=[CENTRO_COSTO, CUENTA_CONTABLE], ascending=True, preagg=preagg,
    )


def detail_by_cuenta(df: pd.DataFrame, partidas: list[str],
                     ascending: bool = False,
                     with_total_row: bool = False,
                     preagg: pd.DataFrame | None = None) -> pd.DataFrame:
    """Filter to *partidas* and pivot by CUENTA_CONTABLE + DESCRIPCION."""
    return _detail_pivot(df, partidas, [CUENTA_CONTABLE, DESCRIPCION],
                         ascending=ascending, with_total_row=with_total_row, preagg=preagg)


def detail_planilla(df: pd.DataFrame,
                    preagg: pd.DataFrame | None = None) -> pd.DataFrame:
    """Pivot ALL partidas for 'planilla' accounts (CUENTA_CONTABLE prefix '62')
    by PARTIDA_PL x CENTRO_COSTO x DESC_CECO x CUENTA_CONTABLE x DESCRIPCION.

    Returns a flat DataFrame with month columns + TOTAL, sorted by
    PARTIDA_PL then CENTRO_COSTO then CUENTA_CONTABLE.
    """
    source = preagg if preagg is not None else df
    source = source[source[CUENTA_CONTABLE].str.startswith("62")]
    if source.empty:
        return pd.DataFrame()
    index_cols = [PARTIDA_PL, CENTRO_COSTO, DESC_CECO,
                  CUENTA_CONTABLE, DESCRIPCION]
    pivot = pivot_by_month(source, index_cols, add_total=True)
    return pivot.sort_values(
        [PARTIDA_PL, CENTRO_COSTO, CUENTA_CONTABLE], ascending=True,
    ).reset_index(drop=True)


CECO_TRANSPORTE = "100.113.01"

ALLOWED_PROVEEDORES_CECOS = [
    "100.113.01",
    "100.115.01",
    "100.112.01",
    "100.107.01",
    "100.114.01",
    "100.117.01",
    "100.118.01",
]


def detail_proveedores_by_ceco(df: pd.DataFrame, ceco: str = CECO_TRANSPORTE) -> pd.DataFrame:
    """Pivot a specific CENTRO_COSTO by NIT + RAZON_SOCIAL x month."""
    if ceco not in ALLOWED_PROVEEDORES_CECOS:
        raise ValueError(f"CECO {ceco!r} not in allowed list")
    filtered = df[df[CENTRO_COSTO] == ceco]
    if filtered.empty:
        return pd.DataFrame()
    filtered = filtered.copy()
    filtered[NIT] = filtered[NIT].fillna("SIN NIT")
    filtered[RAZON_SOCIAL] = filtered[RAZON_SOCIAL].fillna("SIN RAZON SOCIAL")
    pivot = pivot_by_month(filtered, [NIT, RAZON_SOCIAL], add_total=True)
    pivot = pivot.sort_values(TOTAL_COL, ascending=False).reset_index(drop=True)
    pivot = append_total_row(pivot, RAZON_SOCIAL)
    return pivot


def detail_proveedores_transporte(df: pd.DataFrame) -> pd.DataFrame:
    """Pivot COSTO DE TRANSPORTE (CECO 100.113.01) by NIT + RAZON_SOCIAL x month."""
    return detail_proveedores_by_ceco(df, CECO_TRANSPORTE)


def split_resultado_financiero(res_fin_df: pd.DataFrame, sort_col: str = TOTAL_COL,
                               gastos_ascending: bool = True) -> ResultadoFinanciero:
    """Split a RESULTADO FINANCIERO DataFrame into ingresos (prefix '77') and gastos.

    Parameters
    ----------
    res_fin_df : pd.DataFrame
        Detail-by-cuenta pivot for RESULTADO FINANCIERO.
    sort_col : str
        Column to sort by (e.g. "TOTAL" for Excel, a period column for PDF).
    gastos_ascending : bool
        Sort gastos from lowest to highest (True) so most-negative items appear first.

    Returns
    -------
    ResultadoFinanciero(ingresos, gastos) with TOTAL rows appended.
    """
    mask_77 = res_fin_df[CUENTA_CONTABLE].str.startswith(INGRESO_FINANCIERO_PREFIX)
    ingresos = append_total_row(
        res_fin_df[mask_77].reset_index(drop=True), DESCRIPCION,
    )
    gastos_df = res_fin_df[~mask_77].reset_index(drop=True)
    if sort_col in gastos_df.columns:
        gastos_df = gastos_df.sort_values(sort_col, ascending=gastos_ascending).reset_index(drop=True)
    gastos = append_total_row(gastos_df, DESCRIPCION)
    return ResultadoFinanciero(ingresos=ingresos, gastos=gastos)


def detail_resultado_financiero(df: pd.DataFrame,
                                preagg: pd.DataFrame | None = None) -> ResultadoFinanciero:
    """Split RESULTADO FINANCIERO into ingresos (account prefix '77') and gastos."""
    res_fin = detail_by_cuenta(df, ["RESULTADO FINANCIERO"], preagg=preagg)
    return split_resultado_financiero(res_fin)


def detail_diferencia_cambio(df: pd.DataFrame,
                             preagg: pd.DataFrame | None = None) -> ResultadoFinanciero:
    """Split DIFERENCIA DE CAMBIO into ingresos (prefix '77.6') and gastos (prefix '67.6')."""
    dif_cambio = detail_by_cuenta(df, ["DIFERENCIA DE CAMBIO"], preagg=preagg)
    return split_resultado_financiero(dif_cambio)


def sales_details(df: pd.DataFrame, with_total_row: bool = False,
                  preagg: pd.DataFrame | None = None) -> pd.DataFrame:
    """Pivot INGRESOS ORDINARIOS by CUENTA_CONTABLE + DESCRIPCION."""
    return _detail_pivot(df, ["INGRESOS ORDINARIOS"], [CUENTA_CONTABLE, DESCRIPCION],
                         with_total_row=with_total_row, preagg=preagg)



# ── BS detail helpers ────────────────────────────────────────────────────────

# Column name emitted by VISTA_BS_PREPARADO_CUMSUM / VISTA_BS_DETALLE_NIT_CUMSUM.
# Not in config.fields because it is a view-output column, like the SALDO_* columns
# that statements.py references directly.
SALDO_CUMSUM = "SALDO_CUMSUM"


def _pivot_cumsum(frame: pd.DataFrame, index_cols: list[str],
                  last_month: int | None) -> pd.DataFrame:
    """Pivot an already-cumulative cumsum-view frame into JAN..DEC columns.

    *frame* has one row per (index_cols, MES) carrying SALDO_CUMSUM — the
    running balance Jan→that month, ALREADY computed densified to 12 months by
    the SQL view.  This does a PLAIN pivot (no second cumsum — re-summing would
    double the balances) and zeroes months after *last_month* so future months
    don't show the carried-forward balance, matching the pre-Phase-F builders.

    Returns the wide pivot with all 12 month columns present in calendar order.
    """
    if frame.empty:
        # No rows (empty partida, or all rows excluded by a cuenta-prefix
        # filter).  pd.pivot_table can't pivot an empty frame, so build the
        # correctly-shaped empty pivot directly: label columns + all 12 months.
        # Month columns must be float dtype (not object) so a downstream
        # append_total_row sums them to 0.0, not None — matching the pre-Phase-F
        # path where the empty pivot's months came from pivot_table fill_value=0.
        empty = pd.DataFrame(columns=[*index_cols, *MONTH_NAMES_LIST])
        return empty.astype({m: "float64" for m in MONTH_NAMES_LIST})
    pivot = pd.pivot_table(
        frame, values=SALDO_CUMSUM, index=index_cols,
        columns=MES, aggfunc="sum", fill_value=0, observed=True, sort=False,
    )
    pivot.columns = [MONTH_NAMES[int(c)] for c in pivot.columns]
    pivot = pivot.reset_index()
    pivot = ensure_month_columns(pivot)
    if last_month is not None:
        future_cols = MONTH_NAMES_LIST[last_month:]  # 0-indexed JAN..DEC
        if future_cols:
            pivot[future_cols] = 0
    return pivot


def bs_detail_by_cuenta(frame: pd.DataFrame, *,
                        last_month: int | None,
                        add_total_col: bool = True,
                        cuenta_prefixes: tuple[str, ...] | None = None,
                        exclude_cuenta_prefixes: tuple[str, ...] | None = None) -> pd.DataFrame:
    """Build the cuenta-grain BS note table from a cumsum-view frame.

    *frame* comes from VISTA_BS_PREPARADO_CUMSUM (already filtered to the note's
    PARTIDA_BS list in SQL), with columns MES, CUENTA_CONTABLE, DESCRIPCION,
    SALDO_CUMSUM.  The cumulative-sum + densification happened in SQL; here we
    only apply the cuenta-prefix include/exclude, pivot to JAN..DEC, zero future
    months, set TOTAL, and sort.

    When *add_total_col* is False the TOTAL column is omitted.
    *cuenta_prefixes* / *exclude_cuenta_prefixes* match on CUENTA_CONTABLE.
    """
    filtered = frame
    if cuenta_prefixes is not None:
        filtered = filtered[filtered[CUENTA_CONTABLE].str.startswith(cuenta_prefixes)]
    if exclude_cuenta_prefixes is not None:
        filtered = filtered[~filtered[CUENTA_CONTABLE].str.startswith(exclude_cuenta_prefixes)]
    # Empty input (or everything excluded) flows through too: _pivot_cumsum
    # returns a correctly-columned empty pivot so the TOTAL column/row stay
    # zero-filled across JAN..DEC, matching the pre-Phase-F shape.
    pivot = _pivot_cumsum(filtered, [CUENTA_CONTABLE, DESCRIPCION], last_month)
    # Sort by last-activity month's cumulative value (Dec is zeroed for future
    # months, so use last_month rather than the trailing display column).
    sort_col = MONTH_NAMES_LIST[last_month - 1] if last_month else CUENTA_CONTABLE
    if add_total_col:
        if last_month:
            pivot[TOTAL_COL] = pivot[MONTH_NAMES_LIST[last_month - 1]]
        else:
            pivot[TOTAL_COL] = 0
        sort_col = TOTAL_COL
    return pivot.sort_values(sort_col, ascending=False).reset_index(drop=True)


def bs_top20_by_nit(frame: pd.DataFrame, *,
                    last_month: int | None,
                    top_n: int = 20) -> pd.DataFrame:
    """Build the NIT top-N BS note table from a cumsum-view frame.

    *frame* comes from VISTA_BS_DETALLE_NIT_CUMSUM (already filtered to the
    note's PARTIDA_BS list in SQL), with columns MES, NIT, RAZON_SOCIAL,
    SALDO_CUMSUM.  Fills SIN NIT / SIN RAZON SOCIAL (the view leaves NULLs
    unfilled by design), pivots, zeroes future months, ranks by the
    last-activity month descending, takes top N, and appends a TOTAL row.
    """
    if frame.empty:
        return pd.DataFrame()

    frame = frame.copy()
    frame[NIT] = frame[NIT].fillna("SIN NIT")
    frame[RAZON_SOCIAL] = frame[RAZON_SOCIAL].fillna("SIN RAZON SOCIAL")

    pivot = _pivot_cumsum(frame, [NIT, RAZON_SOCIAL], last_month)

    # Rank by last-activity-month cumulative desc, NIT asc as a deterministic
    # tiebreak — matching VISTA_BS_DETALLE_NIT_CUMSUM's server-side ROW_NUMBER
    # ordering, so the final top-N cut is reproducible regardless of the order
    # the umbrella UNION ALL delivers rows in.
    if last_month:
        pivot = pivot.sort_values(
            [MONTH_NAMES_LIST[last_month - 1], NIT], ascending=[False, True]
        ).reset_index(drop=True)
    else:
        pivot = pivot.sort_values(NIT).reset_index(drop=True)
    pivot = pivot.head(top_n).reset_index(drop=True)
    pivot = append_total_row(pivot, RAZON_SOCIAL)
    return pivot


def proyectos_especiales(df: pd.DataFrame, mes_cols: list[str],
                         with_total_row: bool = False) -> pd.DataFrame:
    """Pivot INGRESOS PROYECTOS by NIT + RAZON_SOCIAL, ensuring all *mes_cols* present."""
    df = df[df[PARTIDA_PL] == "INGRESOS PROYECTOS"]
    pivot = pivot_by_month(df, [NIT, RAZON_SOCIAL])
    # Union of caller's months and pivot's own months to avoid silent dropping
    pivot_months = {c for c in pivot.columns if c in MONTH_NAMES_SET}
    all_months = sorted(set(mes_cols) | pivot_months, key=MONTH_NAMES_LIST.index)
    for col in all_months:
        if col not in pivot.columns:
            pivot[col] = 0
    pivot[TOTAL_COL] = pivot[all_months].sum(axis=1)
    pivot = pivot[[NIT, RAZON_SOCIAL] + all_months + [TOTAL_COL]]
    pivot = pivot.sort_values(TOTAL_COL, ascending=False).reset_index(drop=True)
    if with_total_row:
        pivot = append_total_row(pivot, RAZON_SOCIAL)
    return pivot


# ── Period aggregation helpers ───────────────────────────────────────────────

def sum_for_months(df: pd.DataFrame, index_cols: list[str],
                   months: list[int]) -> pd.Series:
    """Filter *df* to *months*, group by *index_cols*, and sum SALDO.

    Always returns a Series whose index carries the correct name(s),
    even when *df* is empty, so that ``pd.DataFrame({...})`` built from
    multiple calls keeps the index columns aligned.
    """
    filtered = df[df[MES].isin(months)] if not df.empty else df
    if filtered.empty:
        if len(index_cols) == 1:
            idx = pd.Index([], name=index_cols[0])
        else:
            idx = pd.MultiIndex.from_tuples([], names=index_cols)
        return pd.Series(dtype=float, index=idx)
    return filtered.groupby(index_cols, observed=True)[SALDO].sum()


def aggregate_period(df_current: pd.DataFrame, df_prev: pd.DataFrame,
                     period_type: str, period_num: int | None, year: int,
                     index_cols: list[str], col_names: tuple) -> pd.DataFrame:
    """Build a DataFrame with period + YTD columns for current and previous year.

    Parameters
    ----------
    df_current, df_prev : pd.DataFrame
        Prepared statement data for the current and previous year.
    period_type : str
        "month", "quarter", or "year".
    period_num : int or None
        Month (1-12), quarter (1-4), or None for year.
    year : int
    index_cols : list[str]
        Columns to group by (e.g. ["PARTIDA_PL"]).
    col_names : tuple
        4 strings (month/quarter) or 2 strings (year) used as column headers.

    Returns
    -------
    pd.DataFrame with *index_cols* + value columns.
    """
    period_months = get_period_months(period_type, period_num)
    ytd_months = get_ytd_months(period_type, period_num)

    if period_type == "year":
        current_total = sum_for_months(df_current, index_cols, period_months)
        prev_total = sum_for_months(df_prev, index_cols, period_months)
        result = pd.DataFrame({
            col_names[0]: current_total,
            col_names[1]: prev_total,
        })
    else:
        current_period = sum_for_months(df_current, index_cols, period_months)
        prev_period = sum_for_months(df_prev, index_cols, period_months)
        current_ytd = sum_for_months(df_current, index_cols, ytd_months)
        prev_ytd = sum_for_months(df_prev, index_cols, ytd_months)
        result = pd.DataFrame({
            col_names[0]: current_period,
            col_names[1]: prev_period,
            col_names[2]: current_ytd,
            col_names[3]: prev_ytd,
        })

    return result.fillna(0).reset_index()


def merge_current_prev(current: pd.DataFrame, prev: pd.DataFrame | None,
                       join_key: str, col_names: tuple[str, str],
                       keep_months: list[str],
                       output_cols: list[str]) -> pd.DataFrame:
    """Merge current-year and previous-year DataFrames into a 2-column layout.

    Renames the single month column to the year label, left-joins on *join_key*,
    and fills missing previous-year values with zero.

    Parameters
    ----------
    current, prev : pd.DataFrame or None
        Current and previous year data.  *prev* may be None or empty.
    join_key : str
        Column name to merge on (e.g. "PARTIDA_BS", "CUENTA_CONTABLE", "NIT").
    col_names : tuple[str, str]
        (current_year_label, previous_year_label).
    keep_months : list[str]
        Single-element list with the month column to rename.
    output_cols : list[str]
        Final column order for the returned DataFrame.
    """
    month_col = keep_months[0]

    if month_col in current.columns:
        current = current.rename(columns={month_col: col_names[0]})
    elif col_names[0] not in current.columns:
        current[col_names[0]] = 0

    if prev is not None and not prev.empty and month_col in prev.columns:
        prev = prev.rename(columns={month_col: col_names[1]})
        merged = current.merge(prev[[join_key, col_names[1]]],
                               on=join_key, how="left")
        merged[col_names[1]] = merged[col_names[1]].fillna(0)
    else:
        merged = current.copy()
        merged[col_names[1]] = 0

    # Guarantee all output columns exist even when the frame is empty
    for c in output_cols:
        if c not in merged.columns:
            merged[c] = 0

    return merged[output_cols]
