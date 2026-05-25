"""Account classification rules — P&L display helpers, BS mappings, display order.

P&L row-level classification was moved to REPORTES.VISTA_PNL_PREPARADO in
Phase A of SQL_VIEWS_ROADMAP.md; BS row-level classification was moved to
REPORTES.VISTA_BS_PREPARADO in Phase B. What remains here is display-only:
partida ordering, subtotal labels, CORRIENTE/NO CORRIENTE membership, and
the cumsum-time reclassification rules that statements.bs_summary still
applies in Python.
"""


# ── P&L display helpers ──────────────────────────────────────────────────────

DETAIL_CATEGORIES = ["COSTO", "GASTO VENTA", "GASTO ADMIN", "OTROS EGRESOS"]

PL_SUBTOTAL_LABELS = {
    "INGRESOS TOTALES",
    "UTILIDAD BRUTA",
    "UTILIDAD OPERATIVA",
    "UTILIDAD ANTES DE IMPUESTO A LA RENTA",
    "UTILIDAD NETA",
}

INGRESO_FINANCIERO_PREFIX = "77"

# ── Balance Sheet display helpers ────────────────────────────────────────────

# Display order for BS partidas within each section
BS_PARTIDA_ORDER = [
    # Activo
    "Efectivo y equivalentes de efectivo",
    "Cuentas por cobrar comerciales (neto)",
    "Otras cuentas por cobrar relacionadas",
    "Otras cuentas por cobrar (neto)",
    "Existencias",
    "Anticipos Otorgados",
    "Propiedades, planta y equipo (neto)",
    "Intangible",
    "Inversiones Mobiliarias",
    "Activo Diferido",
    "Otros Activos",
    "Tributos por acreditar",
    # Pasivo
    "Cuentas por pagar comerciales",
    "Otras cuentas por Pagar Relacionadas",
    "Otras cuentas por pagar",
    "Tributos por Pagar",
    "Provisiones por beneficios a empleados",
    "Anticipos Recibidos",
    "Obligaciones Financieras",
    "Impuesto a la renta diferido",
    "Participaciones de los trabajadores diferidas",
    "Intereses diferidos",
    # Patrimonio
    "Capital Emitido",
    "Aportes",
    "Excedente de revaluación",
    "Reservas",
    "Resultados Acumulados",
    "Resultados del Ejercicio",
]

# Dynamic reclassification: accounts that move between sections when cumulative
# SALDO is negative.  Each rule is (prefix, match_mode, target_partida, target_section).
# match_mode: "exact" = cuenta_code must equal prefix; "prefix" = startswith.
# Rules are evaluated in order; first match wins.
BS_RECLASSIFICATION_RULES: list[tuple[str, str, str, str]] = [
    ("12.2.1.1.01", "exact",  "Anticipos Recibidos",                     "PASIVO"),
    ("14",          "prefix", "Provisiones por beneficios a empleados",   "PASIVO"),
    ("42.2",        "prefix", "Anticipos Otorgados",                      "ACTIVO"),
]

BS_SECTION_ORDER = ["ACTIVO", "PASIVO", "PATRIMONIO"]

# Maps account first character to its native BS section.
# Used by _native_section() to determine default classification.
BS_NATIVE_SECTION_MAP: dict[str, str] = {
    "1": "ACTIVO",
    "2": "ACTIVO",
    "3": "ACTIVO",
    "4": "PASIVO",
    "5": "PATRIMONIO",
}

# Sub-section classification: partidas that belong to NO CORRIENTE.
# Everything not listed here defaults to CORRIENTE for its section.
# PATRIMONIO has no CORRIENTE / NO CORRIENTE split.
BS_ACTIVO_NO_CORRIENTE = frozenset({
    "Propiedades, planta y equipo (neto)",
})

BS_PASIVO_NO_CORRIENTE = frozenset({
    "Impuesto a la renta diferido",
    "Participaciones de los trabajadores diferidas",
    "Intereses diferidos",
})

BS_SUBTOTAL_LABELS = {
    "TOTAL ACTIVO CORRIENTE", "TOTAL ACTIVO NO CORRIENTE",
    "TOTAL ACTIVO",
    "TOTAL PASIVO CORRIENTE", "TOTAL PASIVO NO CORRIENTE",
    "TOTAL PASIVO",
    "TOTAL PATRIMONIO", "TOTAL PASIVO Y PATRIMONIO",
}

BS_PARTIDA_LABELS = frozenset({
    "ACTIVO CORRIENTE",
    "ACTIVO NO CORRIENTE",
    "Activo Diferido",
    "Anticipos Otorgados",
    "Anticipos Recibidos",
    "Aportes",
    "Capital Emitido",
    "Cuentas por cobrar comerciales (neto)",
    "Cuentas por pagar comerciales",
    "Efectivo y equivalentes de efectivo",
    "Excedente de revaluación",
    "Existencias",
    "Impuesto a la renta diferido",
    "Intangible",
    "Intereses diferidos",
    "Inversiones Mobiliarias",
    "Obligaciones Financieras",
    "Otras cuentas por Pagar Relacionadas",
    "Otras cuentas por cobrar (neto)",
    "Otras cuentas por cobrar relacionadas",
    "Otras cuentas por pagar",
    "Otros Activos",
    "PASIVO CORRIENTE",
    "PASIVO NO CORRIENTE",
    "POR DEFINIR ACTIVO",
    "POR DEFINIR PASIVO",
    "POR DEFINIR PATRIMONIO",
    "Participaciones de los trabajadores diferidas",
    "Propiedades, planta y equipo (neto)",
    "Provisiones por beneficios a empleados",
    "Reservas",
    "Resultados Acumulados",
    "Resultados del Ejercicio",
    "Tributos por Pagar",
    "Tributos por acreditar",
})

# ── BS account-prefix → display-group mappings ───────────────────────────
# Used by both Excel and PDF export for grouping detail rows by category.
# Rules are evaluated in order; the FIRST matching prefix wins.

BS_EFECTIVO_GROUPS: list[tuple[str, str]] = [
    ("10.1.", "Caja chica"),
    ("10.2.", "Caja chica"),
    ("10.3.", "Caja chica"),
    ("10.4.", "Cuentas corrientes"),
    ("10.6.", "Depositos a plazo"),
    ("10.7.", "Caja chica"),
]

BS_CXC_COMERCIALES_GROUPS: list[tuple[str, str]] = [
    ("12.1.1", "Documentos por Cobrar No emitidos"),
    ("12.1",   "Documentos por Cobrar"),
    ("12.2",   "Anticipos de Clientes"),
    ("12.3",   "Letras por Cobrar"),
    ("19.1",   "Deterioro de Cuentas por Cobrar"),
]

BS_CXC_OTRAS_GROUPS: list[tuple[str, str]] = [
    ("14.1",   "Cuentas por Cobrar al Personal"),
    ("14.2",   "Cuentas por Cobrar a Accionistas o Directores"),
    ("14.3",   "Cuentas por Cobrar a Accionistas o Directores"),
    ("14.9",   "Cuentas por Cobrar Diversas"),
    ("16.1",   "Prestamos por Cobrar"),
    ("16.2",   "Cuentas por Cobrar Diversas"),
    ("16.3",   "Cuentas por Cobrar Diversas"),
    ("16.4",   "Depositos en garantia"),
    ("16.5",   "Cuentas por Cobrar Diversas"),
    ("16.6",   "Cuentas por Cobrar Diversas"),
    ("16.7",   "Tributos por Cobrar"),
    ("16.9",   "Cuentas por Cobrar Diversas"),
]

BS_PPE_GROUPS: list[tuple[str, str]] = [
    ("33.0",   "Planta productora"),
    ("33.1",   "Terrenos"),
    ("33.2",   "Edificaciones"),
    ("33.3",   "Maquinaria y equipo de explotación"),
    ("33.4",   "Unidades de transporte"),
    ("33.5",   "Muebles y enseres"),
    ("33.6",   "Equipos diversos"),
    ("33.7",   "Herramientas y unidades de reemplazo"),
    ("33.8",   "Unidades por recibir"),
    ("33.9",   "Obras en curso"),
    ("32.1",   "Propiedades de inversión - Arrendamiento financiero"),
    ("32.2",   "Propiedad, planta y equipo - Arrendamiento financiero"),
    ("32.3",   "Propiedad, planta y equipo - Arrendamiento operativo"),
]

BS_PPE_DEPRECIACION_GROUPS: list[tuple[str, str]] = [
    ("39.1",   "Depreciación acum. propiedades de inversión"),
    ("39.4",   "Depreciación acum. - Arrendamiento Operativo"),
    ("39.5",   "Depreciación acum. de propiedad, planta y equipo"),
    ("39.6",   "Amortización acumulada"),
]

BS_TRIBUTOS_GROUPS: list[tuple[str, str]] = [
    ("40.1.1", "Impuesto general a las ventas"),
    ("40.1.2", "Impuesto selectivo al consumo"),
    ("40.1.5", "Derechos aduaneros"),
    ("40.1.7", "Impuesto a la renta"),
    ("40.1.8", "Otros impuestos y contraprestaciones"),
    ("40.2",   "Certificados tributarios"),
    ("40.3",   "Instituciones publicas"),
    ("40.5",   "Gobiernos regionales"),
    ("40.6",   "Gobiernos locales"),
    ("16.7",   "Tributos por acreditar"),
]


def get_bs_group(cuenta: str, group_table: list[tuple[str, str]]) -> str | None:
    """Return the group label for a CUENTA_CONTABLE from *group_table*, or None."""
    for prefix, label in group_table:
        if str(cuenta).startswith(prefix):
            return label
    return None


# Mapping from bs_key to its group table (used by both Excel and PDF)
BS_GROUP_TABLES: dict[str, list[tuple[str, str]]] = {
    "bs_efectivo":          BS_EFECTIVO_GROUPS,
    "bs_cxc_comerciales":   BS_CXC_COMERCIALES_GROUPS,
    "bs_cxc_otras":         BS_CXC_OTRAS_GROUPS,
    "bs_ppe":               BS_PPE_GROUPS,
    "bs_ppe_depreciacion":  BS_PPE_DEPRECIACION_GROUPS,
    "bs_tributos":          BS_TRIBUTOS_GROUPS,
}
