import logging

import numpy as np
import pandas as pd

from calendar_config import MONTH_NAMES, MONTH_NAMES_SET
from account_rules import (
    BS_SECTION_ORDER,
    BS_RECLASS_ANTICIPO_CUENTA, BS_RECLASS_14_TO_PASIVO,
    BS_RECLASS_42_2_TO_ACTIVO, BS_PARTIDA_ORDER,
    BS_ACTIVO_NO_CORRIENTE, BS_PASIVO_NO_CORRIENTE,
)
from aggregation import TOTAL_COL, pivot_by_month, _apply_bs_cumsum
from exceptions import DataValidationError


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
        "D&A - GASTO", "PROVISION INCOBRABLE", "OTROS INGRESOS",
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
        ["UTILIDAD OPERATIVA"] + utilidad_op.tolist(),
        [""] + [None] * len(val_cols),
        data_row("RESULTADO FINANCIERO"),
        data_row("DIFERENCIA DE CAMBIO"),
        ["UTILIDAD ANTES DE IMPUESTO A LA RENTA"] + utilidad_air.tolist(),
        [""] + [None] * len(val_cols),
        data_row("IMPUESTO A LA RENTA"),
        ["UTILIDAD NETA"] + utilidad_neta.tolist(),
    ]

    if "POR DEFINIR" in lookup:
        rows.append([""] + [None] * len(val_cols))
        rows.append(data_row("POR DEFINIR"))

    return pd.DataFrame(rows, columns=["PARTIDA_PL"] + val_cols)


def build_partida_lookup(pivot, val_cols):
    """Build a {PARTIDA_PL: numpy_array} lookup from a pivoted DataFrame."""
    partida_values = pivot["PARTIDA_PL"].tolist()
    numeric_matrix = pivot[val_cols].values.astype(float)
    return {partida: numeric_matrix[i] for i, partida in enumerate(partida_values)}


def pl_summary(df):
    pivot = pivot_by_month(df, "PARTIDA_PL", add_total=True)
    mes_cols = [c for c in pivot.columns if c in MONTH_NAMES_SET]
    val_cols = mes_cols + [TOTAL_COL]
    lookup = build_partida_lookup(pivot, val_cols)
    return build_pl_rows(lookup, val_cols)


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

    def get(name):
        return partida_lookup.get(name, zeros)

    # Group partidas by section
    by_section = {s: [] for s in BS_SECTION_ORDER}
    for partida, section in section_map.items():
        if section in by_section:
            by_section[section].append(partida)

    # Sort partidas by BS_PARTIDA_ORDER; unlisted ones go to the end alphabetically
    order_index = {name: i for i, name in enumerate(BS_PARTIDA_ORDER)}

    rows = []
    section_totals = {}

    # Map section -> set of NO CORRIENTE partida names
    _no_corriente_map = {
        "ACTIVO": BS_ACTIVO_NO_CORRIENTE,
        "PASIVO": BS_PASIVO_NO_CORRIENTE,
    }

    def _emit_partidas(partida_list):
        """Emit partida header + detail rows, return subtotal array."""
        sub = zeros.copy()
        for p in partida_list:
            vals = get(p)
            if np.allclose(vals, 0):
                continue
            rows.append([p] + vals.tolist())
            if include_detail:
                for cuenta_label, cuenta_vals in cuenta_detail.get(p, []):
                    if not np.allclose(cuenta_vals, 0):
                        rows.append([f"  {cuenta_label}"] + cuenta_vals.tolist())
            sub += vals
        return sub

    for section in BS_SECTION_ORDER:
        partidas = sorted(
            by_section[section],
            key=lambda p: (order_index.get(p, len(BS_PARTIDA_ORDER)), p),
        )

        no_corriente_set = _no_corriente_map.get(section)

        if no_corriente_set is not None:
            # --- CORRIENTE / NO CORRIENTE split ---
            corriente = [p for p in partidas if p not in no_corriente_set]
            no_corriente = [p for p in partidas if p in no_corriente_set]

            # CORRIENTE sub-section
            rows.append([f"{section} CORRIENTE"] + [None] * len(val_cols))
            sub_corriente = _emit_partidas(corriente)
            rows.append([f"TOTAL {section} CORRIENTE"] + sub_corriente.tolist())
            rows.append(blank)

            # NO CORRIENTE sub-section
            rows.append([f"{section} NO CORRIENTE"] + [None] * len(val_cols))
            sub_no_corriente = _emit_partidas(no_corriente)
            rows.append([f"TOTAL {section} NO CORRIENTE"] + sub_no_corriente.tolist())
            rows.append(blank)

            section_total = sub_corriente + sub_no_corriente
        else:
            # --- PATRIMONIO: no sub-section split ---
            section_total = _emit_partidas(partidas)

        section_totals[section] = section_total
        rows.append([f"TOTAL {section}"] + section_total.tolist())
        rows.append(blank)

    total_pasivo_patrimonio = section_totals["PASIVO"] + section_totals["PATRIMONIO"]
    rows.append(["TOTAL PASIVO Y PATRIMONIO"] + total_pasivo_patrimonio.tolist())

    if not np.isclose(section_totals["ACTIVO"][-1], total_pasivo_patrimonio[-1], atol=0.01):
        msg = (
            f"BS imbalance: ACTIVO={section_totals['ACTIVO'][-1]:.2f}, "
            f"PASIVO+PATRIMONIO={total_pasivo_patrimonio[-1]:.2f}"
        )
        if strict_balance:
            raise DataValidationError(msg)
        logger.warning(msg)

    return pd.DataFrame(rows, columns=["PARTIDA_BS"] + val_cols)


def _native_section(cuenta_code):
    """Return the native BS section based on account first character."""
    first = cuenta_code[0]
    if first in ("1", "2", "3"):
        return "ACTIVO"
    if first == "4":
        return "PASIVO"
    return "PATRIMONIO"


def _reclassify_bs_cuentas(cuenta_rows, val_cols):
    """Apply reclassification rules and fix sign for cross-section overrides.

    Returns a list of (partida, seccion, cuenta_code, label, vals) tuples
    with reclassified entries moved to their target partida/section.
    """
    result = []
    for partida, seccion, cuenta_code, label, vals in cuenta_rows:
        last_val = vals[-1]

        # Rule 1: 12.2.1.1.01 negative → PASIVO "Anticipos Recibidos"
        if cuenta_code == BS_RECLASS_ANTICIPO_CUENTA and last_val < 0:
            vals = -vals  # flip sign (was asset-convention, now liability-convention)
            result.append(("Anticipos Recibidos", "PASIVO", cuenta_code, label, vals))
            continue

        # Rule 2: prefix 14 negative → PASIVO "Provisiones por beneficios a empleados"
        if cuenta_code.startswith(BS_RECLASS_14_TO_PASIVO) and last_val < 0:
            vals = -vals
            result.append(("Provisiones por beneficios a empleados", "PASIVO",
                           cuenta_code, label, vals))
            continue

        # Rule 3: prefix 42.2 negative → ACTIVO "Anticipos Otorgados"
        if cuenta_code.startswith(BS_RECLASS_42_2_TO_ACTIVO) and last_val < 0:
            vals = -vals  # flip sign (was liability-convention, now asset-convention)
            result.append(("Anticipos Otorgados", "ACTIVO", cuenta_code, label, vals))
            continue

        # Static cross-section overrides: flip sign when account's native section
        # differs from its assigned section (e.g. class 1 account assigned to PASIVO)
        native = _native_section(cuenta_code)
        if native != seccion:
            vals = -vals

        result.append((partida, seccion, cuenta_code, label, vals))
    return result


def extract_utilidad_neta(pl_df, bs_val_cols):
    """Extract cumulative UTILIDAD NETA from a P&L summary for the BS.

    The P&L summary has monthly *flow* values (each month independent).
    The BS needs *cumulative* values (running total through each month).

    Parameters
    ----------
    pl_df : pd.DataFrame
        The P&L summary DataFrame (output of ``pl_summary()``).
    bs_val_cols : list[str]
        The month column names used in the BS (e.g. ["JAN", "FEB", ...]).

    Returns
    -------
    np.ndarray
        Cumulative UTILIDAD NETA aligned to bs_val_cols, or None if not found.
    """
    row = pl_df[pl_df["PARTIDA_PL"] == "UTILIDAD NETA"]
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
    return np.cumsum(monthly)


def bs_summary(df, *, include_detail=True, pl_summary_df=None, strict_balance=False,
               keep_months: list[str] | None = None):
    """BS summary with monthly cumulative columns, account detail per partida.

    Parameters
    ----------
    pl_summary_df : pd.DataFrame or None
        The P&L summary DataFrame (output of ``pl_summary()``).
        When provided, cumulative UTILIDAD NETA is injected as
        "Resultados del Ejercicio" in PATRIMONIO.
    strict_balance : bool
        If True, raise DataValidationError on BS imbalance instead of warning.
    keep_months : list[str] or None
        Month column names to keep in the output (e.g. ["DEC"]).
        When None all months present in the data are shown.
    """
    # Cuenta-level pivot (finest grain — we'll aggregate partidas from this)
    cuenta_pivot = pivot_by_month(
        df, ["PARTIDA_BS", "SECCION_BS", "CUENTA_CONTABLE", "DESCRIPCION"],
        add_total=False,
    )
    cuenta_pivot, mes_cols, val_cols = _apply_bs_cumsum(cuenta_pivot, keep_months)

    # Build raw cuenta rows
    partida_list = cuenta_pivot["PARTIDA_BS"].tolist()
    seccion_list = cuenta_pivot["SECCION_BS"].tolist()
    cuenta_list = cuenta_pivot["CUENTA_CONTABLE"].tolist()
    desc_list = cuenta_pivot["DESCRIPCION"].tolist()
    val_matrix = cuenta_pivot[val_cols].values.astype(float)
    raw_rows = [
        (partida, seccion, cuenta, f"{cuenta}  {desc}", vals)
        for partida, seccion, cuenta, desc, vals
        in zip(partida_list, seccion_list, cuenta_list, desc_list, val_matrix)
    ]

    # Apply dynamic reclassification
    reclass_rows = _reclassify_bs_cuentas(raw_rows, val_cols)

    # Rebuild partida lookups and cuenta detail from reclassified data
    zeros = np.zeros(len(val_cols))
    partida_lookup = {}
    section_map = {}
    cuenta_detail = {}

    for partida, seccion, cuenta_code, label, vals in reclass_rows:
        # Accumulate partida totals
        if partida not in partida_lookup:
            partida_lookup[partida] = zeros.copy()
            section_map[partida] = seccion
        partida_lookup[partida] += vals

        # Collect detail lines
        cuenta_detail.setdefault(partida, []).append((label, vals))

    # Sort detail lines by cuenta within each partida
    for partida in cuenta_detail:
        cuenta_detail[partida].sort(key=lambda x: x[0])

    # Inject "Resultados del Ejercicio" (cumulative UTILIDAD NETA from P&L)
    # Use ALL month columns for cumsum (same logic as BS accounts above),
    # then pick only the display columns.
    if pl_summary_df is not None:
        utilidad_neta_all = extract_utilidad_neta(pl_summary_df, mes_cols)
        if utilidad_neta_all is not None:
            # Map month names to their cumulative values
            month_to_cum = dict(zip(mes_cols, utilidad_neta_all))
            # Pick only the display columns (val_cols)
            utilidad_neta = np.array([month_to_cum.get(c, 0.0) for c in val_cols])
            partida_lookup["Resultados del Ejercicio"] = utilidad_neta
            section_map["Resultados del Ejercicio"] = "PATRIMONIO"

    return _build_bs_rows(partida_lookup, cuenta_detail, val_cols, section_map, include_detail=include_detail, strict_balance=strict_balance)
