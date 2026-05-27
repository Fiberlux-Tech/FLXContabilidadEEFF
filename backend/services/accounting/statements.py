import logging

import numpy as np
import pandas as pd

from config.calendar import MONTH_NAMES, MONTH_NAMES_LIST, MONTH_NAMES_SET
from accounting.rules import (
    BS_SECTION_ORDER,
    BS_PARTIDA_ORDER,
    BS_ACTIVO_NO_CORRIENTE, BS_PASIVO_NO_CORRIENTE,
)
from accounting.aggregation import TOTAL_COL, pivot_by_month
from config.exceptions import DataValidationError
from config.fields import PARTIDA_PL, PARTIDA_BS, SECCION_BS, MES, SALDO


logger = logging.getLogger("plantillas.statement_builder")


def build_pl_rows(lookup, val_cols):
    """Build the P&L income-statement row structure from a PARTIDA_PL lookup.

    Parameters
    ----------
    lookup : dict[str, np.ndarray]
        Mapping of PARTIDA_PL label -> numpy array of numeric values.
    val_cols : list[str]
        Column names for the value columns.

    Returns
    -------
    pd.DataFrame with columns ["PARTIDA_PL"] + val_cols.
    """
    zeros = np.zeros(len(val_cols))

    def get(name):
        return lookup.get(name, zeros)

    def data_row(name):
        return [name] + get(name).tolist()

    def sum_rows(*names):
        total = zeros.copy()
        for n in names:
            total += get(n)
        return total

    ingresos_totales = sum_rows("INGRESOS ORDINARIOS", "INGRESOS PROYECTOS")
    utilidad_bruta = ingresos_totales + sum_rows("COSTO", "D&A - COSTO")
    utilidad_op = utilidad_bruta + sum_rows(
        "GASTO VENTA", "GASTO ADMIN", "PARTICIPACION DE TRABAJADORES",
        "D&A - GASTO", "PROVISION INCOBRABLE", "OTROS INGRESOS", "OTROS EGRESOS",
    )
    utilidad_air = utilidad_op + sum_rows("RESULTADO FINANCIERO", "DIFERENCIA DE CAMBIO")
    utilidad_neta = utilidad_air + sum_rows("IMPUESTO A LA RENTA")

    rows = [
        data_row("INGRESOS ORDINARIOS"),
        data_row("INGRESOS PROYECTOS"),
        ["INGRESOS TOTALES"] + ingresos_totales.tolist(),
        [""] + [None] * len(val_cols),
        data_row("COSTO"),
        data_row("D&A - COSTO"),
        ["UTILIDAD BRUTA"] + utilidad_bruta.tolist(),
        [""] + [None] * len(val_cols),
        data_row("GASTO VENTA"),
        data_row("GASTO ADMIN"),
        data_row("PARTICIPACION DE TRABAJADORES"),
        data_row("D&A - GASTO"),
        data_row("PROVISION INCOBRABLE"),
        data_row("OTROS INGRESOS"),
        data_row("OTROS EGRESOS"),
        ["UTILIDAD OPERATIVA"] + utilidad_op.tolist(),
        [""] + [None] * len(val_cols),
        data_row("RESULTADO FINANCIERO"),
        data_row("DIFERENCIA DE CAMBIO"),
        ["UTILIDAD ANTES DE IMPUESTO A LA RENTA"] + utilidad_air.tolist(),
        [""] + [None] * len(val_cols),
        data_row("IMPUESTO A LA RENTA"),
        ["UTILIDAD NETA"] + utilidad_neta.tolist(),
    ]

    if "POR CLASIFICAR" in lookup:
        rows.append([""] + [None] * len(val_cols))
        rows.append(data_row("POR CLASIFICAR"))

    return pd.DataFrame(rows, columns=[PARTIDA_PL] + val_cols)


def build_partida_lookup(pivot, val_cols):
    """Build a {PARTIDA_PL: numpy_array} lookup from a pivoted DataFrame."""
    partida_values = pivot[PARTIDA_PL].tolist()
    numeric_matrix = pivot[val_cols].values.astype(float)
    return {partida: numeric_matrix[i] for i, partida in enumerate(partida_values)}


def _group_partidas_by_section(section_map):
    """Group partida names by their BS section, sorted by BS_PARTIDA_ORDER.

    Returns a dict mapping each section in BS_SECTION_ORDER to a sorted list
    of partida names.
    """
    by_section = {s: [] for s in BS_SECTION_ORDER}
    for partida, section in section_map.items():
        if section in by_section:
            by_section[section].append(partida)

    order_index = {name: i for i, name in enumerate(BS_PARTIDA_ORDER)}
    for section in by_section:
        by_section[section].sort(
            key=lambda p: (order_index.get(p, len(BS_PARTIDA_ORDER)), p),
        )
    return by_section


def _emit_partidas(partida_list, partida_lookup, cuenta_detail, zeros, include_detail):
    """Emit partida header + detail rows and return (rows, subtotal_array).

    For each partida with non-zero values, appends a header row and
    optionally indented cuenta-level detail rows.
    """
    rows = []
    sub = zeros.copy()
    val_len = len(zeros)
    for p in partida_list:
        vals = partida_lookup.get(p, zeros)
        if np.allclose(vals, 0):
            continue
        rows.append([p] + vals.tolist())
        if include_detail:
            for cuenta_label, cuenta_vals in cuenta_detail.get(p, []):
                if not np.allclose(cuenta_vals, 0):
                    rows.append([f"  {cuenta_label}"] + cuenta_vals.tolist())
        sub += vals
    return rows, sub


def _emit_corriente_no_corriente(section, partidas, no_corriente_set,
                                  partida_lookup, cuenta_detail, zeros, include_detail):
    """Emit CORRIENTE / NO CORRIENTE sub-sections for ACTIVO or PASIVO.

    Returns (rows, section_total_array).
    """
    val_len = len(zeros)
    blank = [""] + [None] * val_len
    corriente = [p for p in partidas if p not in no_corriente_set]
    no_corriente = [p for p in partidas if p in no_corriente_set]

    rows = []

    # CORRIENTE sub-section
    rows.append([f"{section} CORRIENTE"] + [None] * val_len)
    corr_rows, sub_corriente = _emit_partidas(
        corriente, partida_lookup, cuenta_detail, zeros, include_detail)
    rows.extend(corr_rows)
    rows.append([f"TOTAL {section} CORRIENTE"] + sub_corriente.tolist())
    rows.append(blank)

    # NO CORRIENTE sub-section
    rows.append([f"{section} NO CORRIENTE"] + [None] * val_len)
    nc_rows, sub_no_corriente = _emit_partidas(
        no_corriente, partida_lookup, cuenta_detail, zeros, include_detail)
    rows.extend(nc_rows)
    rows.append([f"TOTAL {section} NO CORRIENTE"] + sub_no_corriente.tolist())
    rows.append(blank)

    return rows, sub_corriente + sub_no_corriente


def _validate_bs_balance(section_totals, total_pasivo_patrimonio, *, strict_balance):
    """Check that ACTIVO equals PASIVO + PATRIMONIO and log or raise on mismatch."""
    if not np.isclose(section_totals["ACTIVO"][-1], total_pasivo_patrimonio[-1], atol=0.01):
        msg = (
            f"BS imbalance: ACTIVO={section_totals['ACTIVO'][-1]:.2f}, "
            f"PASIVO+PATRIMONIO={total_pasivo_patrimonio[-1]:.2f}"
        )
        if strict_balance:
            raise DataValidationError(msg)
        logger.warning(msg)


def _build_bs_rows(partida_lookup, cuenta_detail, val_cols, section_map, *, include_detail=True, strict_balance=False):
    """Build the BS row structure with account-level detail under each partida.

    Parameters
    ----------
    partida_lookup : dict[str, np.ndarray]
        Mapping of PARTIDA_BS label -> numpy array of totals.
    cuenta_detail : dict[str, list[tuple[str, np.ndarray]]]
        Mapping of PARTIDA_BS -> list of (cuenta_label, values) pairs.
    val_cols : list[str]
        Column names for the value columns (monthly cumulative).
    section_map : dict[str, str]
        Mapping of PARTIDA_BS label -> section (ACTIVO, PASIVO, PATRIMONIO).
    strict_balance : bool
        If True, raise DataValidationError on BS imbalance instead of warning.

    Returns
    -------
    pd.DataFrame with columns ["PARTIDA_BS"] + val_cols.
    """
    zeros = np.zeros(len(val_cols))
    blank = [""] + [None] * len(val_cols)

    by_section = _group_partidas_by_section(section_map)

    # Map section -> set of NO CORRIENTE partida names
    no_corriente_map = {
        "ACTIVO": BS_ACTIVO_NO_CORRIENTE,
        "PASIVO": BS_PASIVO_NO_CORRIENTE,
    }

    rows = []
    section_totals = {}

    for section in BS_SECTION_ORDER:
        partidas = by_section[section]
        no_corriente_set = no_corriente_map.get(section)

        if no_corriente_set is not None:
            sec_rows, section_total = _emit_corriente_no_corriente(
                section, partidas, no_corriente_set,
                partida_lookup, cuenta_detail, zeros, include_detail)
            rows.extend(sec_rows)
        else:
            # PATRIMONIO: no sub-section split
            partida_rows, section_total = _emit_partidas(
                partidas, partida_lookup, cuenta_detail, zeros, include_detail)
            rows.extend(partida_rows)

        section_totals[section] = section_total
        rows.append([f"TOTAL {section}"] + section_total.tolist())
        rows.append(blank)

    total_pasivo_patrimonio = section_totals["PASIVO"] + section_totals["PATRIMONIO"]
    rows.append(["TOTAL PASIVO Y PATRIMONIO"] + total_pasivo_patrimonio.tolist())

    _validate_bs_balance(section_totals, total_pasivo_patrimonio, strict_balance=strict_balance)

    return pd.DataFrame(rows, columns=[PARTIDA_BS] + val_cols)


def extract_utilidad_neta(pl_df, bs_val_cols, last_month: int | None = None):
    """Extract cumulative UTILIDAD NETA from a P&L summary for the BS.

    The P&L summary has monthly *flow* values (each month independent).
    The BS needs *cumulative* values (running total through each month).
    When *last_month* is provided, months after it are zeroed so that future
    periods don't inherit the last closed cumulative balance.

    Parameters
    ----------
    pl_df : pd.DataFrame
        The P&L summary DataFrame (output of ``pl_summary()``).
    bs_val_cols : list[str]
        The month column names used in the BS (e.g. ["JAN", "FEB", ...]).
    last_month : int or None
        Highest month (1–12) with actual BS data. Months beyond this are zeroed.

    Returns
    -------
    np.ndarray
        Cumulative UTILIDAD NETA aligned to bs_val_cols, or None if not found.
    """
    row = pl_df[pl_df[PARTIDA_PL] == "UTILIDAD NETA"]
    if row.empty:
        logger.warning("UTILIDAD NETA not found in P&L — Resultados del Ejercicio will be omitted.")
        return None
    # P&L has month cols + TOTAL; pick only the months present in BS
    vals = []
    for col in bs_val_cols:
        if col in row.columns:
            vals.append(float(row[col].iloc[0] or 0))
        else:
            vals.append(0.0)
    monthly = np.array(vals)
    cumulative = np.cumsum(monthly)
    if last_month is not None:
        for i, col in enumerate(bs_val_cols):
            if col in MONTH_NAMES_SET and MONTH_NAMES_LIST.index(col) >= last_month:
                cumulative[i] = 0.0
    return cumulative


# ── Phase C: view-based summary builders ─────────────────────────────────
#
# These read from the pre-aggregated REPORTES.VISTA_PNL_SUMARIO and
# REPORTES.VISTA_BS_SUMARIO views (Phase C of docs/SQL_VIEWS_ROADMAP.md).
# Classification, GROUP BY, BS cumsum, and BS reclassification all live in
# SQL.  Python's only remaining job is to pivot MES → wide columns and run
# the existing build_pl_rows / _build_bs_rows display-structure helpers.


def _pl_summary_from_long(summary_df: pd.DataFrame, saldo_col: str) -> pd.DataFrame:
    """Build one P&L summary frame from VISTA_PNL_SUMARIO using *saldo_col*.

    *saldo_col* is one of 'SALDO_TOTAL', 'SALDO_EX_IC', 'SALDO_ONLY_IC'.

    SQL's SUM(CASE WHEN cond THEN val END) returns NULL when no source rows
    matched the predicate for that (partida, month).  We use that signal to
    distinguish "no rows existed" (drop the partida from this variant) from
    "rows existed and netted to zero" (keep the zero row, matching the old
    pl_summary contract that pivoted a filtered DataFrame).
    """
    # Drop partidas that had zero source rows in this IC variant — i.e. every
    # MES is NULL.  Rows that have a 0.0 SUM (rows existed, summed to zero)
    # are kept so the partida still appears in the display.
    has_any_row = summary_df.groupby(PARTIDA_PL, observed=True)[saldo_col].apply(lambda s: s.notna().any())
    keep_partidas = has_any_row[has_any_row].index
    long = summary_df[summary_df[PARTIDA_PL].isin(keep_partidas)][[MES, PARTIDA_PL, saldo_col]].copy()
    long[saldo_col] = long[saldo_col].fillna(0)
    long = long.rename(columns={saldo_col: SALDO})
    pivot = pivot_by_month(long, PARTIDA_PL, add_total=True)
    mes_cols = [c for c in pivot.columns if c in MONTH_NAMES_SET]
    val_cols = mes_cols + [TOTAL_COL]
    lookup = build_partida_lookup(pivot, val_cols)
    return build_pl_rows(lookup, val_cols)


def pl_summary_from_view(summary_df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Build the three P&L summary DataFrames from a VISTA_PNL_SUMARIO fetch.

    *summary_df* is the output of data.queries.fetch_pnl_summary (long-form,
    one row per (MES, PARTIDA_PL) with three SALDO columns).  This function
    pivots each SALDO column to wide JAN..DEC + TOTAL and runs build_pl_rows
    for the display structure.

    Returns a dict with keys "total" / "ex_ic" / "only_ic", each a DataFrame
    ready for ensure_month_columns + _df_to_records at the caller.
    """
    return {
        "total":   _pl_summary_from_long(summary_df, "SALDO_TOTAL"),
        "ex_ic":   _pl_summary_from_long(summary_df, "SALDO_EX_IC"),
        "only_ic": _pl_summary_from_long(summary_df, "SALDO_ONLY_IC"),
    }


def bs_summary_from_view(summary_df: pd.DataFrame, *,
                          pl_summary_df: pd.DataFrame | None = None,
                          strict_balance: bool = False,
                          keep_months: list[str] | None = None) -> pd.DataFrame:
    """Build the BS summary DataFrame from a VISTA_BS_SUMARIO fetch.

    *summary_df* is the output of data.queries.fetch_bs_summary (long-form,
    one row per (MES, PARTIDA_BS, SECCION_BS) with the sign-corrected
    cumulative SALDO).  Reclassification + sign flips + cumsum all happened
    in SQL — Python only pivots and renders.

    *pl_summary_df* is the output of pl_summary_from_view()["total"] (or any
    P&L summary with a "UTILIDAD NETA" row).  When provided, cumulative
    UTILIDAD NETA is injected as "Resultados del Ejercicio" in PATRIMONIO.

    *keep_months*: optional list of month column names to keep (e.g. ["DEC"]).
    When None all 12 months are emitted.

    Detail rows (cuenta-grain) are NOT included — VISTA_BS_SUMARIO is
    partida-grain.  All live callers pass include_detail=False, so this is
    feature-parity with bs_summary(df, include_detail=False, ...).
    """
    if summary_df.empty:
        return pd.DataFrame()

    pivot = pivot_by_month(summary_df, [PARTIDA_BS, SECCION_BS], add_total=False)
    # pivot_by_month already calls ensure_month_columns → all 12 months present.
    mes_cols = list(MONTH_NAMES_LIST)
    val_cols = [c for c in mes_cols if keep_months is None or c in keep_months]

    partida_list = pivot[PARTIDA_BS].tolist()
    seccion_list = pivot[SECCION_BS].tolist()
    val_matrix = pivot[val_cols].values.astype(float)

    zeros = np.zeros(len(val_cols))
    partida_lookup: dict[str, np.ndarray] = {}
    section_map: dict[str, str] = {}
    for partida, seccion, vals in zip(partida_list, seccion_list, val_matrix):
        if partida not in partida_lookup:
            partida_lookup[partida] = zeros.copy()
            section_map[partida] = seccion
        partida_lookup[partida] += vals

    # Inject "Resultados del Ejercicio" (cumulative UTILIDAD NETA from P&L).
    # Use the same last_month gating as the old bs_summary: zero out months
    # past max(MES) so a partial-year view doesn't carry the closed cumulative
    # into future months.
    if pl_summary_df is not None:
        last_month = int(summary_df[MES].max())
        utilidad_neta = extract_utilidad_neta(pl_summary_df, val_cols, last_month=last_month)
        if utilidad_neta is not None:
            partida_lookup["Resultados del Ejercicio"] = utilidad_neta
            section_map["Resultados del Ejercicio"] = "PATRIMONIO"

    return _build_bs_rows(
        partida_lookup, {}, val_cols, section_map,
        include_detail=False, strict_balance=strict_balance,
    )
