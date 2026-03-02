from dataclasses import dataclass, field

import pandas as pd



@dataclass
class PeriodContext:
    """Groups the five parameters shared by every public pdf_reports function."""
    df_current: pd.DataFrame
    df_prev: pd.DataFrame
    period_type: str            # "month", "quarter", "year"
    period_num: int | None   # month 1-12, quarter 1-4, or None
    year: int


@dataclass
class PnLReportData:
    detail_by_cuenta: pd.DataFrame          # was "v1"
    detail_by_ceco: pd.DataFrame            # was "v2"
    detail_by_ceco_cuenta: pd.DataFrame     # was "v3"
    excluded_cuentas: set                   # was "excluded"
    pl_summary: pd.DataFrame                # was "pl"
    sales_details: pd.DataFrame             # was "sd"
    proyectos_especiales: pd.DataFrame      # was "pe"
    costo: pd.DataFrame
    costo_expanded: pd.DataFrame            # was "costo_exp"
    gasto_venta: pd.DataFrame
    gasto_venta_expanded: pd.DataFrame      # was "gasto_venta_exp"
    gasto_admin: pd.DataFrame
    gasto_admin_expanded: pd.DataFrame      # was "gasto_admin_exp"
    resultado_financiero_ingresos: pd.DataFrame  # 77* accounts, with TOTAL row
    resultado_financiero_gastos: pd.DataFrame    # non-77* accounts, with TOTAL row
    dya_costo: pd.DataFrame                      # D&A - COSTO by CENTRO_COSTO, with TOTAL row
    dya_gasto: pd.DataFrame                      # D&A - GASTO by CENTRO_COSTO, with TOTAL row
    dya_costo_expanded: pd.DataFrame             # D&A - COSTO by CECO x CUENTA
    dya_gasto_expanded: pd.DataFrame             # D&A - GASTO by CECO x CUENTA
    # Balance-Sheet data — populated by build_bs_data().
    # Keys: "bs_summary", "bs_validador", and one per BS_DETAIL_SHEETS entry.
    bs_sheets: dict[str, pd.DataFrame] = field(default_factory=dict)


@dataclass
class PdfReportData:
    pl_summary: pd.DataFrame                        # Income statement (4 or 2 value columns)
    sales_details: pd.DataFrame                     # INGRESOS ORDINARIOS by CUENTA
    proyectos_especiales: pd.DataFrame              # INGRESOS PROYECTOS by NIT
    costo: pd.DataFrame                             # COSTO by CECO (summary)
    gasto_venta: pd.DataFrame                       # GASTO VENTA by CECO (summary)
    gasto_admin: pd.DataFrame                       # GASTO ADMIN by CECO (summary)
    resultado_financiero_ingresos: pd.DataFrame     # 77* accounts by CUENTA
    resultado_financiero_gastos: pd.DataFrame       # non-77* accounts by CUENTA
    dya_costo: pd.DataFrame                         # D&A - COSTO by CECO
    dya_gasto: pd.DataFrame                         # D&A - GASTO by CECO
    bs_summary: pd.DataFrame                         # Balance sheet (2 value columns)
    # Metadata for the PDF template
    company: str
    year: int
    period_type: str                                # "month", "quarter", "year"
    period_num: int | None                       # month 1-12, quarter 1-4, or None
    column_names: tuple                             # 4 or 2 value column header strings
    # BS detail notes — keyed by note name, each is a CUENTA x 2-column DataFrame
    bs_details: dict[str, pd.DataFrame] = field(default_factory=dict)
    # NIT pivot tables for relacionadas — keyed by nit_pivot_key, value is (current_df, prev_df)
    nit_pivots: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = field(default_factory=dict)
    # Top-N NIT ranking tables — keyed by nit_ranking_key, each is NIT x 2-column DataFrame
    nit_rankings: dict[str, pd.DataFrame] = field(default_factory=dict)
