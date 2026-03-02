"""PDF report data building — transforms raw data into PdfReportData."""

import logging

import pandas as pd

from transforms import prepare_stmt, prepare_bs_stmt
from aggregation import (
    bs_cxc_relacionadas_by_nit,
    bs_cxp_relacionadas_by_nit,
)
from statement_builder import pl_summary
from pdf_reports import (
    build_column_names, build_bs_column_names,
    pl_summary_pdf, bs_summary_pdf, bs_detail_by_cuenta_pdf,
    sales_details_pdf, proyectos_especiales_pdf,
    detail_by_ceco_pdf, detail_resultado_financiero_pdf,
    bs_relacionadas_nit_pdf, bs_top_by_nit_pdf,
)
from models import PdfReportData, PeriodContext


logger = logging.getLogger("plantillas.pdf_builder")

# Import the canonical entries from excel_builder to derive PDF notes
from excel_builder import _BS_DETAIL_ENTRIES

# PDF overrides: wider partida scope for grouped PDF notes
_PDF_PARTIDA_OVERRIDES = {
    "bs_otros_activos": ["Otros Activos", "Existencias", "Anticipos Otorgados",
                         "Inversiones Mobiliarias", "Activo Diferido"],
    "bs_cxp_otras":     ["Otras cuentas por pagar", "Anticipos Recibidos",
                         "Obligaciones Financieras"],
}

# PDF key order (differs from Excel: bs_otros_activos moves after intangible
# block; bs_provisiones and bs_tributos swap)
_PDF_KEY_ORDER = [
    "bs_efectivo", "bs_cxc_comerciales", "bs_cxc_relacionadas", "bs_cxc_otras",
    "bs_ppe", "bs_ppe_depreciacion", "bs_intangible", "bs_intangible_amortizacion",
    "bs_otros_activos",
    "bs_cxp_comerciales", "bs_cxp_relacionadas", "bs_cxp_otras",
    "bs_provisiones", "bs_tributos",
]


def _build_pdf_detail_notes():
    by_key = {key: (key, partidas, incl, excl) for key, partidas, incl, excl in _BS_DETAIL_ENTRIES}
    result = []
    for key in _PDF_KEY_ORDER:
        k, partidas, incl, excl = by_key[key]
        result.append((k, _PDF_PARTIDA_OVERRIDES.get(key, partidas), incl, excl))
    return result


BS_PDF_DETAIL_NOTES = _build_pdf_detail_notes()


def build_pdf_data(raw_current_full: pd.DataFrame, raw_prev: pd.DataFrame,
                   raw_bs: pd.DataFrame, raw_bs_prev: pd.DataFrame,
                   company: str, year: int, period_type: str, period_num: int | None,
                   *, df_bs_prepared: pd.DataFrame | None = None) -> PdfReportData:
    """Transform raw data into the PdfReportData for PDF export."""
    logger.info("Preparing PDF data...")
    df_stmt_current_full = prepare_stmt(raw_current_full)

    if not raw_prev.empty:
        df_stmt_prev = prepare_stmt(raw_prev)
    else:
        df_stmt_prev = pd.DataFrame(columns=df_stmt_current_full.columns)

    ctx = PeriodContext(df_stmt_current_full, df_stmt_prev, period_type, period_num, year)

    pdf_pl = pl_summary_pdf(ctx)
    pdf_sd = sales_details_pdf(ctx, with_total_row=True)
    pdf_pe = proyectos_especiales_pdf(ctx, with_total_row=True)

    pdf_costo = detail_by_ceco_pdf(ctx, ["COSTO"], ascending=True, with_total_row=True)
    pdf_gasto_venta = detail_by_ceco_pdf(ctx, ["GASTO VENTA"], ascending=True, with_total_row=True)
    pdf_gasto_admin = detail_by_ceco_pdf(ctx, ["GASTO ADMIN"], ascending=True, with_total_row=True)

    pdf_res_fin = detail_resultado_financiero_pdf(ctx)

    pdf_dya_costo = detail_by_ceco_pdf(ctx, ["D&A - COSTO"], ascending=True, with_total_row=True)
    pdf_dya_gasto = detail_by_ceco_pdf(ctx, ["D&A - GASTO"], ascending=True, with_total_row=True)

    # --- Balance Sheet ---
    df_bs_current = df_bs_prepared if df_bs_prepared is not None else (
        prepare_bs_stmt(raw_bs) if not raw_bs.empty else pd.DataFrame()
    )
    df_bs_prev = prepare_bs_stmt(raw_bs_prev) if not raw_bs_prev.empty else pd.DataFrame()

    # Build P&L summary for current year (Excel-style, monthly) to extract UTILIDAD NETA
    pl_for_bs = None
    if not df_stmt_current_full.empty:
        pl_for_bs = pl_summary(df_stmt_current_full)

    if not df_bs_current.empty:
        pdf_bs = bs_summary_pdf(
            df_bs_current, df_bs_prev, year, period_type, period_num,
            pl_summary_df=pl_for_bs,
        )
    else:
        logger.warning("No BS data for PDF — balance sheet page will be empty.")
        bs_cols = list(build_bs_column_names(year))
        pdf_bs = pd.DataFrame(columns=["PARTIDA_BS"] + bs_cols)

    # BS detail notes
    bs_details = {}
    for key, partidas, incl_pf, excl_pf in BS_PDF_DETAIL_NOTES:
        bs_details[key] = bs_detail_by_cuenta_pdf(
            df_bs_current, df_bs_prev, year, period_type, period_num,
            partidas, cuenta_prefixes=incl_pf, exclude_cuenta_prefixes=excl_pf,
            with_total_row=True,
        )

    # NIT pivot tables for relacionadas (one per year)
    nit_pivots = {}
    for nit_key, partida_fn in (
        ("bs_cxc_relacionadas_nit", bs_cxc_relacionadas_by_nit),
        ("bs_cxp_relacionadas_nit", bs_cxp_relacionadas_by_nit),
    ):
        cur = bs_relacionadas_nit_pdf(df_bs_current, period_type, period_num, partida_fn)
        prev = bs_relacionadas_nit_pdf(df_bs_prev, period_type, period_num, partida_fn)
        nit_pivots[nit_key] = (cur, prev)

    # Top-N NIT ranking tables for CxC and CxP notas (PDF: top 5)
    nit_rankings = {}
    PDF_NIT_RANKING_SHEETS = [
        ("bs_cxc_comerciales_nit_top20", ["Cuentas por cobrar comerciales (neto)"]),
        ("bs_cxc_otras_nit_top20",       ["Otras cuentas por cobrar (neto)"]),
        ("bs_cxp_comerciales_nit_top20", ["Cuentas por pagar comerciales"]),
        ("bs_cxp_otras_nit_top20",       ["Otras cuentas por pagar"]),
    ]
    for key, partidas in PDF_NIT_RANKING_SHEETS:
        nit_rankings[key] = bs_top_by_nit_pdf(
            df_bs_current, df_bs_prev, year, period_type, period_num,
            partidas, top_n=5,
        )

    return PdfReportData(
        pl_summary=pdf_pl,
        sales_details=pdf_sd,
        proyectos_especiales=pdf_pe,
        costo=pdf_costo,
        gasto_venta=pdf_gasto_venta,
        gasto_admin=pdf_gasto_admin,
        resultado_financiero_ingresos=pdf_res_fin.ingresos,
        resultado_financiero_gastos=pdf_res_fin.gastos,
        dya_costo=pdf_dya_costo,
        dya_gasto=pdf_dya_gasto,
        bs_summary=pdf_bs,
        bs_details=bs_details,
        nit_pivots=nit_pivots,
        nit_rankings=nit_rankings,
        company=company,
        year=year,
        period_type=period_type,
        period_num=period_num,
        column_names=build_column_names(period_type, period_num, year),
    )
