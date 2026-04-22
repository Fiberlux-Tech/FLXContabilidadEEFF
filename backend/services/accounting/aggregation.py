import logging
from collections import namedtuple

import pandas as pd

from config.calendar import MONTH_NAMES, MONTH_NAMES_LIST, MONTH_NAMES_SET
from config.fields import (
    CUENTA_CONTABLE, DESCRIPCION, PARTIDA_PL, PARTIDA_BS,
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


def sales_details(df: pd.DataFrame, with_total_row: bool = False,
                  preagg: pd.DataFrame | None = None) -> pd.DataFrame:
    """Pivot INGRESOS ORDINARIOS by CUENTA_CONTABLE + DESCRIPCION."""
    return _detail_pivot(df, ["INGRESOS ORDINARIOS"], [CUENTA_CONTABLE, DESCRIPCION],
                         with_total_row=with_total_row, preagg=preagg)



# ── BS detail helpers ────────────────────────────────────────────────────────

def last_data_month(df: pd.DataFrame) -> int | None:
    """Return the highest MES (1–12) present in *df*, or None if empty.

    Used to distinguish closed months (cumsum carries balance forward) from
    future months (should display as 0 / blank, not the last closed balance).
    """
    if df.empty or MES not in df.columns:
        return None
    max_mes = df[MES].max()
    return int(max_mes) if pd.notna(max_mes) else None


def _apply_bs_cumsum(
    pivot: pd.DataFrame,
    keep_months: list[str] | None = None,
    last_month: int | None = None,
) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Ensure 12 month columns exist, reorder to calendar order, cumsum, filter.

    When *last_month* is given (1–12), month columns after that are zeroed out
    AFTER cumsum so future months don't inherit the last closed balance.

    Returns (pivot_with_cumsum_applied, all_month_cols, display_month_cols).
    """
    pivot = ensure_month_columns(pivot)
    pivot[MONTH_NAMES_LIST] = pivot[MONTH_NAMES_LIST].cumsum(axis=1)
    if last_month is not None:
        future_cols = MONTH_NAMES_LIST[last_month:]  # MONTH_NAMES_LIST is 0-indexed JAN..DEC
        if future_cols:
            pivot[future_cols] = 0
    if keep_months is not None:
        display_cols = [c for c in MONTH_NAMES_LIST if c in keep_months]
    else:
        display_cols = list(MONTH_NAMES_LIST)
    return pivot, MONTH_NAMES_LIST, display_cols


def bs_detail_by_cuenta(df: pd.DataFrame, partidas: list[str], *,
                        add_total_col: bool = True,
                        keep_months: list[str] | None = None,
                        cuenta_prefixes: tuple[str, ...] | None = None,
                        exclude_cuenta_prefixes: tuple[str, ...] | None = None) -> pd.DataFrame:
    """Pivot BS data for the given PARTIDA_BS values by CUENTA_CONTABLE + DESCRIPCION.

    Filters on PARTIDA_BS (not PARTIDA_PL) and applies cumulative month logic.
    When *add_total_col* is False the TOTAL column is omitted (detail sheets).
    When *keep_months* is provided, only those month columns are kept in the
    output (after cumsum so values are still cumulative).
    When *cuenta_prefixes* is provided, only accounts starting with those prefixes are included.
    When *exclude_cuenta_prefixes* is provided, accounts starting with those prefixes are excluded.
    """
    filtered = df[df[PARTIDA_BS].isin(partidas)]
    if cuenta_prefixes is not None:
        filtered = filtered[filtered[CUENTA_CONTABLE].str.startswith(cuenta_prefixes)]
    if exclude_cuenta_prefixes is not None:
        filtered = filtered[~filtered[CUENTA_CONTABLE].str.startswith(exclude_cuenta_prefixes)]
    pivot = pivot_by_month(filtered, [CUENTA_CONTABLE, DESCRIPCION], add_total=False)
    last_month = last_data_month(df)
    pivot, mes_cols, display_cols = _apply_bs_cumsum(
        pivot, keep_months, last_month=last_month,
    )
    # Sort by last displayed month's cumulative value. When no keep_months
    # filter is set, display_cols ends at DEC which would be zeroed for future
    # months; fall back to the last month with actual data.
    if keep_months is None and last_month is not None:
        sort_col = MONTH_NAMES_LIST[last_month - 1]
    else:
        sort_col = display_cols[-1] if display_cols else CUENTA_CONTABLE
    if add_total_col:
        # TOTAL = cumulative as of the last month with actual data (not Dec,
        # which would be 0 after future-month zeroing).
        if mes_cols:
            total_src_col = MONTH_NAMES_LIST[last_month - 1] if last_month else mes_cols[-1]
            pivot[TOTAL_COL] = pivot[total_src_col]
        else:
            pivot[TOTAL_COL] = 0
        sort_col = TOTAL_COL
    pivot = pivot.sort_values(sort_col, ascending=False).reset_index(drop=True)
    # Drop month columns outside the requested period
    if keep_months is not None:
        drop_cols = [c for c in mes_cols if c not in keep_months]
        pivot = pivot.drop(columns=drop_cols)
    return pivot


def bs_top20_by_nit(df: pd.DataFrame, partidas: list[str], *,
                    keep_months: list[str] | None = None,
                    top_n: int = 20) -> pd.DataFrame:
    """Pivot BS data by NIT + RAZON_SOCIAL x month, cumulative, top N by last period.

    Follows the same cumulative logic as bs_detail_by_cuenta():
    filters by PARTIDA_BS, pivots by NIT + RAZON_SOCIAL, applies cumsum,
    ranks by the last displayed month column (descending), takes top N,
    and appends a TOTAL row.
    """
    filtered = df[df[PARTIDA_BS].isin(partidas)]
    if filtered.empty:
        return pd.DataFrame()

    filtered = filtered.copy()
    filtered[NIT] = filtered[NIT].fillna("SIN NIT")
    filtered[RAZON_SOCIAL] = filtered[RAZON_SOCIAL].fillna("SIN RAZON SOCIAL")

    pivot = pivot_by_month(filtered, [NIT, RAZON_SOCIAL], add_total=False)
    last_month = last_data_month(df)
    pivot, mes_cols, display_cols = _apply_bs_cumsum(
        pivot, keep_months, last_month=last_month,
    )

    # Sort by raw value of last displayed month (descending — largest positive first).
    # When no keep_months filter is set, display_cols goes through DEC which would
    # be zeroed for future months; fall back to the last month with actual data.
    if keep_months is None and last_month is not None:
        sort_col = MONTH_NAMES_LIST[last_month - 1]
    else:
        sort_col = display_cols[-1] if display_cols else NIT
    pivot = pivot.sort_values(sort_col, ascending=False).reset_index(drop=True)

    # Take top N
    pivot = pivot.head(top_n).reset_index(drop=True)

    # Drop month columns outside the requested period
    if keep_months is not None:
        drop_cols = [c for c in mes_cols if c not in keep_months]
        pivot = pivot.drop(columns=drop_cols)

    # Append TOTAL row
    pivot = append_total_row(pivot, RAZON_SOCIAL)

    return pivot


def _bs_relacionadas_by_nit(df: pd.DataFrame, partida: str) -> pd.DataFrame:
    """Pivot a BS partida by NIT x CUENTA description, with TOTAL row and column.

    Rows are unique NIT + RAZON_SOCIAL combinations.
    Columns are the DESCRIPCION (name) of each CUENTA_CONTABLE.
    Values are the total SALDO for each NIT / CUENTA combination.
    A TOTAL column and TOTAL row are appended.
    """
    filtered = df[df[PARTIDA_BS] == partida]
    if filtered.empty:
        return pd.DataFrame()
    agg = filtered.groupby([NIT, RAZON_SOCIAL, DESCRIPCION], as_index=False)[SALDO].sum()
    pivot = agg.pivot_table(index=[NIT, RAZON_SOCIAL], columns=DESCRIPCION,
                            values=SALDO, aggfunc="sum", fill_value=0)
    pivot = pivot.reset_index()
    pivot.columns.name = None
    # Add TOTAL column
    value_cols = [c for c in pivot.columns if c not in (NIT, RAZON_SOCIAL)]
    pivot[TOTAL_COL] = pivot[value_cols].sum(axis=1)
    pivot = pivot.sort_values(TOTAL_COL, ascending=False).reset_index(drop=True)
    # Add TOTAL row
    pivot = append_total_row(pivot, RAZON_SOCIAL)
    return pivot


def bs_cxc_relacionadas_by_nit(df: pd.DataFrame) -> pd.DataFrame:
    """Pivot BS 'Otras cuentas por cobrar relacionadas' by NIT x CUENTA description."""
    return _bs_relacionadas_by_nit(df, "Otras cuentas por cobrar relacionadas")


def bs_cxp_relacionadas_by_nit(df: pd.DataFrame) -> pd.DataFrame:
    """Pivot BS 'Otras cuentas por Pagar Relacionadas' by NIT x CUENTA description."""
    return _bs_relacionadas_by_nit(df, "Otras cuentas por Pagar Relacionadas")


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
