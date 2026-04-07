import logging

import pandas as pd

from config.calendar import MONTH_NAMES
from config.fields import (
    CUENTA_CONTABLE, DESCRIPCION, PARTIDA_PL, PARTIDA_BS,
    CENTRO_COSTO, DESC_CECO, NIT, RAZON_SOCIAL, MES,
)
from config.period import get_end_month
from models.models import PeriodContext
from accounting.aggregation import (
    aggregate_period, merge_current_prev,
    append_total_row, split_resultado_financiero,
    bs_detail_by_cuenta, bs_top20_by_nit,
    bs_cxc_relacionadas_by_nit, bs_cxp_relacionadas_by_nit,
)
from accounting.statements import build_pl_rows, build_partida_lookup, bs_summary


logger = logging.getLogger("plantillas.pdf_reports")


def build_column_names(period_type, period_num, year):
    """Return the value column names for the PDF report.

    Month/quarter  → 4 columns: PERIOD current, PERIOD prev, YTD current, YTD prev
    Year           → 2 columns: current year, previous year
    """
    prev_year = year - 1
    if period_type == "month":
        month_label = MONTH_NAMES[period_num]
        return (
            f"{month_label} {year}",
            f"{month_label} {prev_year}",
            f"YTD {year}",
            f"YTD {prev_year}",
        )
    elif period_type == "quarter":
        q_label = f"Q{period_num}"
        return (
            f"{q_label} {year}",
            f"{q_label} {prev_year}",
            f"YTD {year}",
            f"YTD {prev_year}",
        )
    else:  # "year"
        return (str(year), str(prev_year))



def build_bs_column_names(year):
    """Return the 2 value column names for the BS PDF page.

    The balance sheet is a point-in-time snapshot, so we always show exactly
    two columns: the current year vs the previous year.
    """
    return (str(year), str(year - 1))


def _default_sort_col(col_names, period_type):
    """Pick the default sort column: YTD (last) for month/quarter, first for year."""
    return col_names[-1] if period_type != "year" else col_names[0]


# ---------------------------------------------------------------------------
# Public report builders — thin wrappers composing accounting functions
# with PDF column naming
# ---------------------------------------------------------------------------

def pl_summary_pdf(ctx: PeriodContext):
    """Build the income statement for PDF with 4 (or 2) value columns.

    Row structure mirrors reports.pl_summary exactly via shared build_pl_rows.
    """
    col_names = build_column_names(ctx.period_type, ctx.period_num, ctx.year)
    pivot = aggregate_period(
        ctx.df_current, ctx.df_prev, ctx.period_type, ctx.period_num, ctx.year,
        [PARTIDA_PL], col_names,
    )
    val_cols = list(col_names)
    lookup = build_partida_lookup(pivot, val_cols)
    return build_pl_rows(lookup, val_cols)


def bs_summary_pdf(df_bs_current, df_bs_prev, year, period_type, period_num,
                   *, pl_summary_df=None, strict_balance=False):
    """Build the balance sheet for PDF with 2 value columns (current year, previous year).

    The BS is a point-in-time snapshot — we show the cumulative balance at the
    end of the requested period for both the current and previous year.

    Parameters
    ----------
    df_bs_current : pd.DataFrame
        Prepared BS data for the current year (output of ``prepare_bs_stmt()``).
    df_bs_prev : pd.DataFrame
        Prepared BS data for the previous year (output of ``prepare_bs_stmt()``).
    year : int
    period_type : str
    period_num : int or None
    pl_summary_df : pd.DataFrame or None
        P&L summary for current year, used to inject "Resultados del Ejercicio".
    strict_balance : bool
        If True, raise on BS imbalance instead of warning.
    """
    end_month = get_end_month(period_type, period_num)
    keep_months = [MONTH_NAMES[end_month]]

    bs_current = bs_summary(
        df_bs_current, include_detail=False, pl_summary_df=pl_summary_df,
        strict_balance=strict_balance, keep_months=keep_months,
    )

    bs_prev = bs_summary(
        df_bs_prev, include_detail=False, pl_summary_df=None,
        strict_balance=False, keep_months=keep_months,
    ) if not df_bs_prev.empty else None

    col_names = build_bs_column_names(year)

    return merge_current_prev(
        bs_current, bs_prev, PARTIDA_BS, col_names, keep_months,
        [PARTIDA_BS, col_names[0], col_names[1]],
    )


def bs_detail_by_cuenta_pdf(df_bs_current, df_bs_prev, year, period_type, period_num,
                            partidas, *, cuenta_prefixes=None, exclude_cuenta_prefixes=None,
                            with_total_row=False):
    """Build a BS detail-by-cuenta table for PDF with 2 value columns.

    Filters to *partidas*, applies cumsum through the period-end month,
    and merges current vs previous year into a 2-column layout.
    """
    end_month = get_end_month(period_type, period_num)
    keep_months = [MONTH_NAMES[end_month]]
    col_names = build_bs_column_names(year)

    current = bs_detail_by_cuenta(
        df_bs_current, partidas, add_total_col=False, keep_months=keep_months,
        cuenta_prefixes=cuenta_prefixes, exclude_cuenta_prefixes=exclude_cuenta_prefixes,
    ) if not df_bs_current.empty else pd.DataFrame(columns=[CUENTA_CONTABLE, DESCRIPCION])

    prev = bs_detail_by_cuenta(
        df_bs_prev, partidas, add_total_col=False, keep_months=keep_months,
        cuenta_prefixes=cuenta_prefixes, exclude_cuenta_prefixes=exclude_cuenta_prefixes,
    ) if not df_bs_prev.empty else None

    merged = merge_current_prev(
        current, prev, CUENTA_CONTABLE, col_names, keep_months,
        [CUENTA_CONTABLE, DESCRIPCION, col_names[0], col_names[1]],
    )
    # Sort by current year descending
    merged = merged.sort_values(col_names[0], ascending=False).reset_index(drop=True)

    if with_total_row:
        merged = append_total_row(merged, DESCRIPCION)

    return merged


def _detail_pivot_pdf(ctx: PeriodContext, partidas, index_cols,
                      sort_col=None, ascending=False,
                      with_total_row: bool = False):
    """Filter to *partidas*, aggregate for PDF columns, sort."""
    df_c = ctx.df_current[ctx.df_current[PARTIDA_PL].isin(partidas)]
    df_p = ctx.df_prev[ctx.df_prev[PARTIDA_PL].isin(partidas)] if not ctx.df_prev.empty else ctx.df_prev
    col_names = build_column_names(ctx.period_type, ctx.period_num, ctx.year)
    pivot = aggregate_period(
        df_c, df_p, ctx.period_type, ctx.period_num, ctx.year,
        index_cols, col_names,
    )
    if sort_col and sort_col in pivot.columns:
        pivot = pivot.sort_values(sort_col, ascending=ascending)
    pivot = pivot.reset_index(drop=True)
    if with_total_row:
        pivot = append_total_row(pivot, index_cols[-1])
    return pivot


def detail_by_ceco_pdf(ctx: PeriodContext, partidas, ascending=False,
                       with_total_row: bool = False):
    col_names = build_column_names(ctx.period_type, ctx.period_num, ctx.year)
    sort_col = _default_sort_col(col_names, ctx.period_type)
    return _detail_pivot_pdf(
        ctx, partidas, [CENTRO_COSTO, DESC_CECO],
        sort_col=sort_col, ascending=ascending,
        with_total_row=with_total_row,
    )


def detail_by_cuenta_pdf(ctx: PeriodContext, partidas,
                         with_total_row: bool = False):
    col_names = build_column_names(ctx.period_type, ctx.period_num, ctx.year)
    sort_col = _default_sort_col(col_names, ctx.period_type)
    return _detail_pivot_pdf(
        ctx, partidas, [CUENTA_CONTABLE, DESCRIPCION],
        sort_col=sort_col, ascending=False,
        with_total_row=with_total_row,
    )


def detail_resultado_financiero_pdf(ctx: PeriodContext):
    """Split RESULTADO FINANCIERO into ingresos (account prefix '77') and gastos."""
    col_names = build_column_names(ctx.period_type, ctx.period_num, ctx.year)
    sort_col = _default_sort_col(col_names, ctx.period_type)
    res_fin = detail_by_cuenta_pdf(ctx, ["RESULTADO FINANCIERO"])
    return split_resultado_financiero(res_fin, sort_col=sort_col)


def sales_details_pdf(ctx: PeriodContext, with_total_row: bool = False):
    return detail_by_cuenta_pdf(ctx, ["INGRESOS ORDINARIOS"],
                                with_total_row=with_total_row)



def proyectos_especiales_pdf(ctx: PeriodContext,
                             with_total_row: bool = False):
    col_names = build_column_names(ctx.period_type, ctx.period_num, ctx.year)
    sort_col = _default_sort_col(col_names, ctx.period_type)
    return _detail_pivot_pdf(
        ctx, ["INGRESOS PROYECTOS"], [NIT, RAZON_SOCIAL],
        sort_col=sort_col, ascending=False,
        with_total_row=with_total_row,
    )


def bs_relacionadas_nit_pdf(df_bs, period_type, period_num, partida_fn):
    """Build a NIT pivot table for a single year's BS data.

    Filters to months up to the period end, then delegates to the
    existing *partida_fn* (e.g. bs_cxc_relacionadas_by_nit).
    Returns an empty DataFrame when *df_bs* has no data.
    """
    if df_bs.empty:
        return pd.DataFrame()
    end_month = get_end_month(period_type, period_num)
    # MES column is numeric (1-12); keep months 1 through end_month
    filtered = df_bs[df_bs[MES] <= end_month]
    if filtered.empty:
        return pd.DataFrame()
    return partida_fn(filtered)


def bs_top_by_nit_pdf(df_bs_current, df_bs_prev, year, period_type, period_num,
                      partidas, *, top_n=5):
    """Build a Top-N NIT ranking table for PDF with 2 value columns (current vs previous year).

    Uses bs_top20_by_nit() for the heavy lifting (cumsum, ranking), then
    merges current and previous year into the standard 2-column PDF layout.
    """
    end_month = get_end_month(period_type, period_num)
    keep_months = [MONTH_NAMES[end_month]]
    col_names = build_bs_column_names(year)

    current = bs_top20_by_nit(
        df_bs_current, partidas, keep_months=keep_months, top_n=top_n,
    ) if not df_bs_current.empty else pd.DataFrame(columns=[NIT, RAZON_SOCIAL])

    prev = bs_top20_by_nit(
        df_bs_prev, partidas, keep_months=keep_months, top_n=top_n,
    ) if not df_bs_prev.empty else None

    # Remove TOTAL rows before merge (we'll add one at the end on the merged result)
    if not current.empty and RAZON_SOCIAL in current.columns:
        current = current[current[RAZON_SOCIAL] != "TOTAL"].reset_index(drop=True)
    if prev is not None and not prev.empty and RAZON_SOCIAL in prev.columns:
        prev = prev[prev[RAZON_SOCIAL] != "TOTAL"].reset_index(drop=True)

    output_cols = [NIT, RAZON_SOCIAL, col_names[0], col_names[1]]
    merged = merge_current_prev(
        current, prev, NIT, col_names, keep_months, output_cols,
    )

    if merged.empty:
        return pd.DataFrame()
    merged = merged.sort_values(col_names[0], ascending=False).reset_index(drop=True)
    merged = append_total_row(merged, RAZON_SOCIAL)

    return merged
