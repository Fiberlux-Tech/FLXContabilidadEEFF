"""Account classification rules — display-only constants.

All row-level classification + summary aggregation lives in SQL views now:
  * Phase A (2026-05-24): VISTA_PNL_PREPARADO  — P&L classification
  * Phase B (2026-05-25): VISTA_BS_PREPARADO   — BS classification
  * Phase C (2026-05-27): VISTA_PNL_SUMARIO    — P&L summary GROUP BY
                          VISTA_BS_SUMARIO     — BS summary + reclassification
                                                 + cumsum + sign flip

What remains here is display-only: partida ordering and
CORRIENTE/NO CORRIENTE membership used by statements.py, plus the
INGRESO_FINANCIERO_PREFIX constant used by P&L aggregation.
"""


# ── P&L display helpers ──────────────────────────────────────────────────────

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

BS_SECTION_ORDER = ["ACTIVO", "PASIVO", "PATRIMONIO"]

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
