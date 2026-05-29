"""Canonical BS detail note definitions consumed by the dashboard."""

# (key, partidas, cuenta_prefixes, exclude_cuenta_prefixes)
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
