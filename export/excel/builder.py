"""Excel report data building — BS detail sheets and P&L report construction."""

import logging
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from rules.account_rules import DETAIL_CATEGORIES
from config.calendar import MONTH_NAMES, MONTH_NAMES_SET, derive_period_type, get_period_months
from transforms.transforms import (
    prepare_pnl, filter_for_statements, assign_partida_pl,
    prepare_bs_stmt, get_excluded_cuentas,
)
from transforms.aggregation import (
    preaggregate,
    summarize_by_cuenta, summarize_by_ceco, summarize_by_ceco_cuenta,
    detail_by_ceco, detail_ceco_by_cuenta,
    detail_resultado_financiero,
    sales_details, proyectos_especiales,
    bs_detail_by_cuenta,
    bs_top20_by_nit,
    bs_cxc_relacionadas_by_nit,
    bs_cxp_relacionadas_by_nit,
)
from transforms.statement_builder import pl_summary, bs_summary
from models.models import PnLReportData


logger = logging.getLogger("plantillas.excel_builder")

# ── Canonical BS detail entries ───────────────────────────────────────────
# (key, partidas, cuenta_prefixes, exclude_cuenta_prefixes)
# Single source of truth for BS detail sheets/notes. Excel uses these
# directly; PDF uses overridden partidas and a different ordering.
_BS_DETAIL_ENTRIES = [
    ("bs_efectivo",               ["Efectivo y equivalentes de efectivo"],    None,     None),
    ("bs_cxc_comerciales",        ["Cuentas por cobrar comerciales (neto)"],  None,     None),
    ("bs_cxc_relacionadas",       ["Otras cuentas por cobrar relacionadas"],  None,     None),
    ("bs_cxc_otras",              ["Otras cuentas por cobrar (neto)"],        None,     None),
    ("bs_otros_activos",          ["Otros Activos"],                          None,     None),
    ("bs_ppe",                    ["Propiedades, planta y equipo (neto)"],    None,     ("39",)),
    ("bs_ppe_depreciacion",       ["Propiedades, planta y equipo (neto)"],    ("39",),  None),
    ("bs_intangible",             ["Intangible"],                             None,     ("39",)),
    ("bs_intangible_amortizacion",["Intangible"],                             ("39",),  None),
    ("bs_cxp_comerciales",        ["Cuentas por pagar comerciales"],          None,     None),
    ("bs_cxp_relacionadas",       ["Otras cuentas por Pagar Relacionadas"],   None,     None),
    ("bs_cxp_otras",              ["Otras cuentas por pagar"],                None,     None),
    ("bs_tributos",               ["Tributos por Pagar", "Tributos por acreditar"], None, None),
    ("bs_provisiones",            ["Provisiones por beneficios a empleados"], None,     None),
]

BS_DETAIL_SHEETS = list(_BS_DETAIL_ENTRIES)


def build_bs_data(raw_bs: pd.DataFrame, pl_summary_df: pd.DataFrame, report_data: PnLReportData, *,
                  df_bs: pd.DataFrame | None = None,
                  strict_balance: bool = False,
                  month: int | None = None, quarter: int | None = None) -> None:
    """Transform raw BS data and populate BS fields on *report_data*.

    Parameters
    ----------
    raw_bs : pd.DataFrame
        Raw BS rows from ``fetch_bs_data()``.
    pl_summary_df : pd.DataFrame
        P&L summary DataFrame (output of ``pl_summary()``), used to extract
        cumulative UTILIDAD NETA for "Resultados del Ejercicio".
    report_data : PnLReportData
        The report data object whose BS fields will be populated in-place.
    df_bs : pd.DataFrame or None
        Pre-prepared BS DataFrame (output of ``prepare_bs_stmt()``).  When
        provided the raw_bs preparation step is skipped.
    strict_balance : bool
        If True, raise on BS imbalance instead of warning.
    month : int or None
        Selected month (1-12), used to filter displayed columns.
    quarter : int or None
        Selected quarter (1-4), used to filter displayed columns.
    """
    if raw_bs.empty and df_bs is None:
        logger.warning("No BS data returned — BS sheets will be skipped.")
        return
    logger.info("Preparing BS data...")
    df = df_bs if df_bs is not None else prepare_bs_stmt(raw_bs)

    # Determine which month columns to display (matches P&L period filtering)
    period_type, period_num = derive_period_type(month, quarter)
    keep_month_nums = get_period_months(period_type, period_num)
    keep_months = [MONTH_NAMES[m] for m in keep_month_nums]

    bs = report_data.bs_sheets
    bs["bs_summary"] = bs_summary(df, include_detail=False, pl_summary_df=pl_summary_df,
                                  strict_balance=strict_balance, keep_months=keep_months)

    # VALIDADOR_BS: full BS opened by CUENTA_CONTABLE
    bs["bs_validador"] = bs_detail_by_cuenta(df, df["PARTIDA_BS"].unique().tolist(), keep_months=keep_months)

    # Track CUENTA_CONTABLE values with no BS classification (POR DEFINIR)
    _POR_DEFINIR = {"POR DEFINIR ACTIVO", "POR DEFINIR PASIVO", "POR DEFINIR PATRIMONIO"}
    undef_mask = df["PARTIDA_BS"].isin(_POR_DEFINIR)
    bs["bs_undefined_cuentas"] = set(df.loc[undef_mask, "CUENTA_CONTABLE"].unique())

    # Detail sheets by partida (no TOTAL column — cumulative months only)
    for key, partidas, include_pf, exclude_pf in BS_DETAIL_SHEETS:
        bs[key] = bs_detail_by_cuenta(
            df, partidas, add_total_col=False, keep_months=keep_months,
            cuenta_prefixes=include_pf, exclude_cuenta_prefixes=exclude_pf,
        )

    # Top-20 NIT ranking tables for CxC and CxP notas
    BS_NIT_RANKING_SHEETS = [
        ("bs_cxc_comerciales_nit_top20", ["Cuentas por cobrar comerciales (neto)"]),
        ("bs_cxc_otras_nit_top20",       ["Otras cuentas por cobrar (neto)"]),
        ("bs_cxp_comerciales_nit_top20", ["Cuentas por pagar comerciales"]),
        ("bs_cxp_otras_nit_top20",       ["Otras cuentas por pagar"]),
    ]
    for key, partidas in BS_NIT_RANKING_SHEETS:
        bs[key] = bs_top20_by_nit(df, partidas, keep_months=keep_months)

    # NIT x CUENTA cross-tabs for relacionadas
    bs["bs_cxc_relacionadas_nit"] = bs_cxc_relacionadas_by_nit(df)
    bs["bs_cxp_relacionadas_nit"] = bs_cxp_relacionadas_by_nit(df)


def build_excel_data(raw: pd.DataFrame) -> PnLReportData:
    """Transform raw data into the PnLReportData for Excel export."""
    logger.info("Preparing Excel data...")
    df = prepare_pnl(raw)

    by_cuenta = summarize_by_cuenta(df)
    by_ceco = summarize_by_ceco(df)
    by_ceco_cuenta = summarize_by_ceco_cuenta(df)

    df_stmt = filter_for_statements(df)
    excluded = get_excluded_cuentas(df, df_stmt)
    df_stmt = assign_partida_pl(df_stmt)

    pl = pl_summary(df_stmt)

    # Pre-aggregate once; detail pivots reuse this instead of re-scanning raw rows
    preagg = preaggregate(df_stmt)

    # Submit all independent detail pivots concurrently
    futures = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for cat in DETAIL_CATEGORIES:
            key = cat.lower().replace(" ", "_")
            futures[key] = pool.submit(
                detail_by_ceco, df_stmt, [cat],
                ascending=True, with_total_row=True, preagg=preagg,
            )
            futures[f"{key}_exp"] = pool.submit(
                detail_ceco_by_cuenta, df_stmt, [cat], preagg=preagg,
            )

        futures["dya_costo"] = pool.submit(
            detail_by_ceco, df_stmt, ["D&A - COSTO"],
            ascending=True, with_total_row=True, preagg=preagg,
        )
        futures["dya_costo_exp"] = pool.submit(
            detail_ceco_by_cuenta, df_stmt, ["D&A - COSTO"], preagg=preagg,
        )
        futures["dya_gasto"] = pool.submit(
            detail_by_ceco, df_stmt, ["D&A - GASTO"],
            ascending=True, with_total_row=True, preagg=preagg,
        )
        futures["dya_gasto_exp"] = pool.submit(
            detail_ceco_by_cuenta, df_stmt, ["D&A - GASTO"], preagg=preagg,
        )

        futures["res_fin"] = pool.submit(
            detail_resultado_financiero, df_stmt, preagg=preagg,
        )
        futures["sales"] = pool.submit(
            sales_details, df_stmt, with_total_row=True, preagg=preagg,
        )

    # Collect results (raises on first error)
    results = {name: fut.result() for name, fut in futures.items()}

    details = {}
    for cat in DETAIL_CATEGORIES:
        key = cat.lower().replace(" ", "_")
        details[key] = results[key]
        details[f"{key}_exp"] = results[f"{key}_exp"]

    sales = results["sales"]
    mes_cols = [c for c in sales.columns if c in MONTH_NAMES_SET]
    # proyectos_especiales depends on sales' mes_cols, so runs after
    proyectos = proyectos_especiales(df_stmt, mes_cols, with_total_row=True)

    return PnLReportData(
        detail_by_cuenta=by_cuenta,
        detail_by_ceco=by_ceco,
        detail_by_ceco_cuenta=by_ceco_cuenta,
        excluded_cuentas=excluded,
        pl_summary=pl,
        sales_details=sales,
        proyectos_especiales=proyectos,
        costo=details["costo"],
        costo_expanded=details["costo_exp"],
        gasto_venta=details["gasto_venta"],
        gasto_venta_expanded=details["gasto_venta_exp"],
        gasto_admin=details["gasto_admin"],
        gasto_admin_expanded=details["gasto_admin_exp"],
        resultado_financiero_ingresos=results["res_fin"].ingresos,
        resultado_financiero_gastos=results["res_fin"].gastos,
        dya_costo=results["dya_costo"],
        dya_gasto=results["dya_gasto"],
        dya_costo_expanded=results["dya_costo_exp"],
        dya_gasto_expanded=results["dya_gasto_exp"],
    )
