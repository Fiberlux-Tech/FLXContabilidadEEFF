"""Shared note configuration that drives both Excel and PDF rendering.

Reorder or regroup NOTA_GROUPS to change both outputs simultaneously.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum



class RenderPattern(Enum):
    BS_DETAIL = "bs_detail"
    BS_DETAIL_WITH_NIT = "bs_detail_with_nit"
    PL_DETAIL_CECO = "pl_detail_ceco"
    PL_DETAIL_CUENTA = "pl_detail_cuenta"
    SALES_INGRESOS = "sales_ingresos"
    SALES_PROYECTOS = "sales_proyectos"


class DataDomain(Enum):
    BS = "bs"
    PL = "pl"


# ── Label column presets ──────────────────────────────────────────────────

_CUENTA = ("DESCRIPCION",)
_CUENTA_HDR = ("DESCRIPCION",)
_CECO = ("CENTRO_COSTO", "DESC_CECO")
_CECO_HDR = ("CC", "CENTRO DE COSTO")
_NIT = ("NIT", "RAZON_SOCIAL")
_NIT_HDR = ("NIT", "RAZON SOCIAL")
_RAZON = ("RAZON_SOCIAL",)
_RAZON_HDR = ("RAZON SOCIAL",)


@dataclass(frozen=True)
class NotaEntry:
    """One logical note (one numbered sub-header, one table)."""
    label: str
    pattern: RenderPattern
    domain: DataDomain

    bs_key: str | None = None
    nit_pivot_key: str | None = None
    nit_ranking_key: str | None = None
    data_attr: str | None = None

    excel_rename_total_to_year: bool = False

    pdf_label_cols: tuple[str, ...] = _CUENTA
    pdf_header_labels: tuple[str, ...] = _CUENTA_HDR

    # PARTIDA_PL or PARTIDA_BS labels in the summary tables that this nota covers
    partida_labels: tuple[str, ...] = ()

    @property
    def is_bs(self) -> bool:
        return self.domain == DataDomain.BS


@dataclass(frozen=True)
class NotaGroup:
    """One or more notes rendered on the same Excel sheet / PDF page."""
    entries: tuple[NotaEntry, ...]
    skip_empty: bool = True


# ── Helper constructors ──────────────────────────────────────────────────

def _bs(label: str, bs_key: str, partida_labels: tuple[str, ...] = (),
        nit_ranking_key: str | None = None) -> NotaEntry:
    return NotaEntry(label=label, pattern=RenderPattern.BS_DETAIL,
                     domain=DataDomain.BS, bs_key=bs_key,
                     nit_ranking_key=nit_ranking_key,
                     partida_labels=partida_labels)


def _bs_nit(label: str, bs_key: str, nit_key: str, partida_labels: tuple[str, ...] = ()) -> NotaEntry:
    return NotaEntry(label=label, pattern=RenderPattern.BS_DETAIL_WITH_NIT,
                     domain=DataDomain.BS, bs_key=bs_key, nit_pivot_key=nit_key,
                     partida_labels=partida_labels)


def _pl_ceco(label: str, attr: str, partida_labels: tuple[str, ...] = ()) -> NotaEntry:
    return NotaEntry(label=label, pattern=RenderPattern.PL_DETAIL_CECO,
                     domain=DataDomain.PL, data_attr=attr,
                     pdf_label_cols=_CECO, pdf_header_labels=_CECO_HDR,
                     partida_labels=partida_labels)


def _pl_cuenta(label: str, attr: str, partida_labels: tuple[str, ...] = ()) -> NotaEntry:
    return NotaEntry(label=label, pattern=RenderPattern.PL_DETAIL_CUENTA,
                     domain=DataDomain.PL, data_attr=attr,
                     partida_labels=partida_labels)


# ═══════════════════════════════════════════════════════════════════════════
# MASTER CONFIG — reorder this list to change both Excel and PDF output
# ═══════════════════════════════════════════════════════════════════════════

NOTA_GROUPS: tuple[NotaGroup, ...] = (
    # --- BS Notes ---

    NotaGroup(entries=(
        _bs("Efectivo y Equivalentes de Efectivo", "bs_efectivo",
            partida_labels=("Efectivo y equivalentes de efectivo",)),
    )),

    NotaGroup(entries=(
        _bs("Cuentas por Cobrar Comerciales", "bs_cxc_comerciales",
            partida_labels=("Cuentas por cobrar comerciales (neto)",),
            nit_ranking_key="bs_cxc_comerciales_nit_top20"),
    )),

    NotaGroup(entries=(
        _bs("Otras Cuentas por Cobrar", "bs_cxc_otras",
            partida_labels=("Otras cuentas por cobrar (neto)",),
            nit_ranking_key="bs_cxc_otras_nit_top20"),
    )),

    NotaGroup(entries=(
        _bs_nit("Cuentas por Cobrar Relacionadas",
                "bs_cxc_relacionadas", "bs_cxc_relacionadas_nit",
                partida_labels=("Otras cuentas por cobrar relacionadas",)),
    )),

    NotaGroup(entries=(
        _bs("Propiedades, Planta y Equipo", "bs_ppe",
            partida_labels=("Propiedades, planta y equipo (neto)",)),
        _bs("Depreciacion", "bs_ppe_depreciacion"),
        _bs("Intangible", "bs_intangible",
            partida_labels=("Intangible",)),
        _bs("Amortizacion", "bs_intangible_amortizacion"),
    )),

    NotaGroup(entries=(
        _bs("Otros Activos", "bs_otros_activos",
            partida_labels=("Otros Activos",)),
    )),

    NotaGroup(entries=(
        _bs("Cuentas por Pagar Comerciales", "bs_cxp_comerciales",
            partida_labels=("Cuentas por pagar comerciales",),
            nit_ranking_key="bs_cxp_comerciales_nit_top20"),
    )),

    NotaGroup(entries=(
        _bs("Otras Cuentas por Pagar", "bs_cxp_otras",
            partida_labels=("Otras cuentas por pagar",),
            nit_ranking_key="bs_cxp_otras_nit_top20"),
    )),

    NotaGroup(entries=(
        _bs_nit("Cuentas por Pagar Relacionadas",
                "bs_cxp_relacionadas", "bs_cxp_relacionadas_nit",
                partida_labels=("Otras cuentas por Pagar Relacionadas",)),
    )),

    NotaGroup(entries=(
        _bs("Provisiones por Beneficios a Empleados", "bs_provisiones",
            partida_labels=("Provisiones por beneficios a empleados",)),
    )),

    NotaGroup(entries=(
        _bs("Tributos por Pagar", "bs_tributos",
            partida_labels=("Tributos por Pagar", "Tributos por acreditar")),
    )),

    # --- P&L Notes ---

    NotaGroup(entries=(
        NotaEntry(label="Ingresos Ordinarios",
                  pattern=RenderPattern.SALES_INGRESOS,
                  domain=DataDomain.PL, data_attr="sales_details",
                  excel_rename_total_to_year=True,
                  partida_labels=("INGRESOS ORDINARIOS",)),
        NotaEntry(label="Ingresos de Proyectos",
                  pattern=RenderPattern.SALES_PROYECTOS,
                  domain=DataDomain.PL, data_attr="proyectos_especiales",
                  excel_rename_total_to_year=True,
                  pdf_label_cols=_RAZON, pdf_header_labels=_RAZON_HDR,
                  partida_labels=("INGRESOS PROYECTOS",)),
    )),

    NotaGroup(entries=(
        _pl_ceco("Costo de Operaciones", "costo",
                 partida_labels=("COSTO",)),
    )),

    NotaGroup(entries=(
        _pl_ceco("Gastos de Ventas", "gasto_venta",
                 partida_labels=("GASTO VENTA",)),
    )),

    NotaGroup(entries=(
        _pl_ceco("Gastos de Administracion", "gasto_admin",
                 partida_labels=("GASTO ADMIN",)),
    )),

    NotaGroup(entries=(
        _pl_ceco("Depreciacion y Amortizacion (Costo)", "dya_costo",
                 partida_labels=("D&A - COSTO",)),
        _pl_ceco("Depreciacion y Amortizacion (Gasto)", "dya_gasto",
                 partida_labels=("D&A - GASTO",)),
    )),

    NotaGroup(entries=(
        _pl_cuenta("Ingresos Financieros", "resultado_financiero_ingresos",
                   partida_labels=("RESULTADO FINANCIERO",)),
        _pl_cuenta("Gastos Financieros", "resultado_financiero_gastos",
                   partida_labels=("RESULTADO FINANCIERO",)),
    )),
)


# ── Numbering utility ────────────────────────────────────────────────────

def numbered_groups(has_data_fn=None):
    """Yield (group, [(nota_num, entry), ...]) with auto-incrementing numbers.

    Empty entries (where *has_data_fn* returns False) are skipped and
    do not consume a nota number.  Groups with no surviving entries are
    omitted entirely.
    """
    result = []
    nota = 1
    for group in NOTA_GROUPS:
        numbered_entries = []
        for entry in group.entries:
            if has_data_fn is not None and not has_data_fn(entry):
                continue
            numbered_entries.append((nota, entry))
            nota += 1
        if numbered_entries:
            result.append((group, numbered_entries))
    return result


def nota_title(num: int, label: str) -> str:
    return f"Nota {num:02d}. {label}"


def build_partida_nota_map(has_data_fn=None):
    """Return {partida_label: nota_str} for all entries with partida_labels defined.

    When multiple nota entries share the same partida_label (e.g. RESULTADO FINANCIERO
    covered by both Ingresos Financieros and Gastos Financieros), the numbers are
    combined as "06 & 07".
    """
    result = {}  # partida_label -> list of nota nums
    for group, numbered_entries in numbered_groups(has_data_fn):
        for num, entry in numbered_entries:
            for label in entry.partida_labels:
                result.setdefault(label, []).append(num)
    return {k: " & ".join(f"{n:02d}" for n in v) for k, v in result.items()}
