"""DataFrame column name constants — single source of truth.

Import these instead of using bare string literals for column names.
Keeps column references consistent across transforms, aggregation,
statements, export, and data service modules.
"""

# ── Account & description columns ───────────────────────────────────────
CUENTA_CONTABLE = "CUENTA_CONTABLE"
DESCRIPCION = "DESCRIPCION"
ASIENTO = "ASIENTO"

# ── Classification / partida columns ────────────────────────────────────
PARTIDA_PL = "PARTIDA_PL"
PARTIDA_BS = "PARTIDA_BS"
SECCION_BS = "SECCION_BS"

# ── Cost center columns ────────────────────────────────────────────────
CENTRO_COSTO = "CENTRO_COSTO"
DESC_CECO = "DESC_CECO"

# ── Value / measure columns ─────────────────────────────────────────────
SALDO = "SALDO"
FECHA = "FECHA"

# ── Third-party identification ──────────────────────────────────────────
NIT = "NIT"
RAZON_SOCIAL = "RAZON_SOCIAL"

# ── Derived columns (created during transforms) ────────────────────────
FIRST_CHAR = "FIRST_CHAR"
MES = "MES"
IS_INTERCOMPANY = "IS_INTERCOMPANY"
