"""Unified BS detail note definitions — single source of truth for Excel and PDF.

Excel and PDF use the same canonical list of BS detail entries but with
different partida scopes and ordering.  Both consumers import from here
instead of maintaining their own copies.
"""

# ── Canonical BS detail entries ───────────────────────────────────────────
# (key, partidas, cuenta_prefixes, exclude_cuenta_prefixes)
# This is the master list.  Excel uses it directly; PDF applies overrides.

BS_DETAIL_ENTRIES = [
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

# Convenience alias used by Excel builder
BS_DETAIL_SHEETS = list(BS_DETAIL_ENTRIES)


# ── PDF overrides ─────────────────────────────────────────────────────────
# Wider partida scope for grouped PDF notes

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
    by_key = {key: (key, partidas, incl, excl) for key, partidas, incl, excl in BS_DETAIL_ENTRIES}
    result = []
    for key in _PDF_KEY_ORDER:
        k, partidas, incl, excl = by_key[key]
        result.append((k, _PDF_PARTIDA_OVERRIDES.get(key, partidas), incl, excl))
    return result


BS_PDF_DETAIL_NOTES = _build_pdf_detail_notes()

# ── NIT ranking entries (shared by Excel and PDF builders) ───────────────
# (key, partidas) — Excel uses top-20; PDF uses top-5.

BS_NIT_RANKING_ENTRIES = [
    ("bs_cxc_comerciales_nit_top20", ["Cuentas por cobrar comerciales (neto)"]),
    ("bs_cxc_otras_nit_top20",       ["Otras cuentas por cobrar (neto)"]),
    ("bs_cxp_comerciales_nit_top20", ["Cuentas por pagar comerciales"]),
    ("bs_cxp_otras_nit_top20",       ["Otras cuentas por pagar"]),
]
