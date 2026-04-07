import pandas as pd

from models.models import PnLReportData
from accounting.aggregation import TOTAL_COL, append_total_row
from config.fields import CUENTA_CONTABLE
from accounting.rules import get_bs_group, BS_GROUP_TABLES
from config.nota import RenderPattern
from config.nota_utils import numbered_groups, nota_title
from excel.styles import (
    # Constants
    COL_B_WIDTH_PL, COL_B_WIDTH_BS,
    TITLE_ROW, DATA_START_ROW, DATA_START_COL, HEADER_ROW,
    SALES_PANDAS_STARTROW, SALES_HEADER_ROW,
    EXPANDED_GAP_ROWS, PE_GAP_ROWS,
    COL_B,
    PL_SUBTOTAL_LABELS, BS_SUBTOTAL_LABELS,
    # Styling functions
    style_init, style_two_table_sheet,
    apply_number_format, highlight_excluded_rows, highlight_undefined_bs_rows,
    format_subtotal_rows,
    style_validator_sheets, style_pl_sheet, style_bs_sheet,
    format_bs_partida_rows,
    style_detalle_cc_x_cc, style_sales_details,
    style_sheet,
)


VALIDATOR_TAB_COLOR = "8B0000"  # Dark red


def _has_data(df: pd.DataFrame | None) -> bool:
    """Return True if *df* is a non-empty DataFrame."""
    return df is not None and not df.empty


# ── Sheet init / write ───────────────────────────────────────────────────────

def _init_sheet(ws, title):
    """Write only the title text to the standard title cell (B2)."""
    ws.cell(row=TITLE_ROW, column=COL_B, value=title)


def _write_sheet(writer, df, sheet_name, title):
    """Write a single DataFrame to a new sheet with a title in B2."""
    df.to_excel(writer, sheet_name=sheet_name, index=False,
                startrow=DATA_START_ROW, startcol=DATA_START_COL)
    ws = writer.sheets[sheet_name]
    _init_sheet(ws, title)


def _write_table_block(ws, sheet_name, writer, label_row, title, df):
    """Write a subsequent table block at *label_row* and return the next available label_row."""
    ws.cell(row=label_row, column=COL_B, value=title)
    df.to_excel(writer, sheet_name=sheet_name, index=False,
                startrow=label_row + 1, startcol=DATA_START_COL)
    header_row_n = label_row + 2
    return header_row_n + len(df) + EXPANDED_GAP_ROWS + 1


def _write_two_table_sheet(writer, sheet_name, title1, df1, title2, df2):
    """Write two tables on one sheet. Styling deferred to Phase 2."""
    _write_sheet(writer, df1, sheet_name, title1)
    ws = writer.sheets[sheet_name]
    label_row = HEADER_ROW + len(df1) + EXPANDED_GAP_ROWS + 1
    _write_table_block(ws, sheet_name, writer, label_row, title2, df2)


# ── DETALLE_CC_x_CC (5 expanded sections on one sheet) ──────────────────────

def _write_detalle_cc_x_cc(writer, data):
    """Write the five expanded CECO x CUENTA detail sections on one sheet."""
    sheet_name = "DETALLE_CC_x_CC"
    sections = [
        ("xx. DETALLE DE COSTOS",        data.costo_expanded),
        ("xx. DETALLE DE GASTO VENTA",   data.gasto_venta_expanded),
        ("xx. DETALLE DE GASTO ADMIN",   data.gasto_admin_expanded),
        ("xx. DETALLE DE OTROS EGRESOS", data.otros_egresos_expanded),
        ("xx. D&A - COSTO",             data.dya_costo_expanded),
        ("xx. D&A - GASTO",             data.dya_gasto_expanded),
    ]

    first_label, first_df = sections[0]
    _write_sheet(writer, first_df, sheet_name, first_label)
    ws = writer.sheets[sheet_name]

    label_excel_row = HEADER_ROW + len(first_df) + EXPANDED_GAP_ROWS + 1

    for label, df in sections[1:]:
        ws.cell(row=label_excel_row, column=COL_B, value=label)
        df.to_excel(writer, sheet_name=sheet_name, index=False,
                    startrow=label_excel_row, startcol=DATA_START_COL)
        label_excel_row = label_excel_row + 1 + len(df) + EXPANDED_GAP_ROWS + 1


# ── SALES DETAILS ────────────────────────────────────────────────────────────

def _write_sales_details(writer, sections, year, sheet_name):
    """Write the SALES DETAILS sheet with N sales tables stacked vertically.

    *sections* is a list of (title, df) tuples.
    """
    if not sections:
        return
    first_title, first_df = sections[0]
    first_df = first_df.rename(columns={TOTAL_COL: str(year)})
    first_df.to_excel(writer, sheet_name=sheet_name, index=False,
                      startrow=SALES_PANDAS_STARTROW, startcol=DATA_START_COL)
    ws = writer.sheets[sheet_name]
    _init_sheet(ws, first_title)

    start_row = SALES_HEADER_ROW + len(first_df) + 1 + PE_GAP_ROWS
    for title, df in sections[1:]:
        df = df.rename(columns={TOTAL_COL: str(year)})
        ws.cell(row=start_row, column=COL_B, value=title)
        df.to_excel(writer, sheet_name=sheet_name, index=False,
                    startrow=start_row, startcol=DATA_START_COL)
        start_row += len(df) + 1 + PE_GAP_ROWS


# ── BS detail sheets ─────────────────────────────────────────────────────────

def _write_multi_table_sheet(writer, sheet_name, sections):
    """Write N tables stacked vertically on one sheet.

    Each section is either:
      (title, df)               -- TOTAL row appended with label_col="CUENTA_CONTABLE"
      (title, df, label_col)    -- TOTAL row appended with given label_col
      (title, df, None)         -- no TOTAL row appended (caller already added it)
    """
    def _prepare(section):
        if len(section) == 2:
            title, df = section
            return title, append_total_row(df, CUENTA_CONTABLE)
        title, df, label_col = section
        if label_col is not None:
            return title, append_total_row(df, label_col)
        return title, df

    first_title, first_df = _prepare(sections[0])
    _write_sheet(writer, first_df, sheet_name, first_title)
    ws = writer.sheets[sheet_name]

    label_row = HEADER_ROW + len(first_df) + EXPANDED_GAP_ROWS + 1

    for section in sections[1:]:
        title, df = _prepare(section)
        label_row = _write_table_block(ws, sheet_name, writer, label_row, title, df)


def _write_single_bs_sheet(writer, df, sheet_name, title):
    """Write a single-table BS detail sheet with TOTAL row appended."""
    df = append_total_row(df, CUENTA_CONTABLE)
    _write_sheet(writer, df, sheet_name, title)


def _write_relacionadas_sheet(writer, sheet_name, title, bs_detail_df, nit_pivot_df):
    """Write a relacionadas sheet: cuenta-detail table + NIT pivot table underneath.

    The NIT pivot table is appended below with a descriptive title.
    NIT and RAZON_SOCIAL header cells are cleared during styling.
    """
    bs_detail_df = append_total_row(bs_detail_df, CUENTA_CONTABLE)
    _write_sheet(writer, bs_detail_df, sheet_name, title)
    if _has_data(nit_pivot_df):
        ws = writer.sheets[sheet_name]
        label_row = HEADER_ROW + len(bs_detail_df) + EXPANDED_GAP_ROWS + 1
        # Derive NIT pivot title from the main sheet title
        if "Pagar" in title:
            nit_title = "DETALLE DE CUENTAS POR PAGAR RELACIONADAS POR EMPRESA"
        else:
            nit_title = "DETALLE DE CUENTAS POR COBRAR RELACIONADAS POR EMPRESA"
        _write_table_block(ws, sheet_name, writer, label_row, nit_title, nit_pivot_df)


# ── Config-driven helpers ────────────────────────────────────────────────────

def _resolve_excel_df(entry, data):
    """Get the DataFrame for an entry from the appropriate data source."""
    if entry.is_bs:
        return data.bs_sheets.get(entry.bs_key)
    return getattr(data, entry.data_attr, None)


def _add_pdf_category_col(df: pd.DataFrame, bs_key: str = "bs_efectivo") -> pd.DataFrame:
    """Add a 'Categoria PDF' column based on the BS key's grouping rules."""
    group_table = BS_GROUP_TABLES.get(bs_key)
    if group_table is None:
        return df
    df = df.copy()
    df["Categoria PDF"] = df[CUENTA_CONTABLE].apply(
        lambda c: get_bs_group(c, group_table) or "Sin clasificar"
    )
    return df


def _write_single_nota(writer, sheet_name, title, entry, df, bs, year):
    """Write a single-entry nota sheet."""
    match entry.pattern:
        case RenderPattern.BS_DETAIL:
            if entry.bs_key in ("bs_efectivo", "bs_cxc_comerciales", "bs_cxc_otras",
                                "bs_ppe", "bs_ppe_depreciacion", "bs_tributos"):
                df = _add_pdf_category_col(df, entry.bs_key)
            _write_single_bs_sheet(writer, df, sheet_name, title)
        case RenderPattern.BS_DETAIL_WITH_NIT:
            nit_df = bs.get(entry.nit_pivot_key)
            _write_relacionadas_sheet(writer, sheet_name, title, df, nit_df)
        case RenderPattern.PL_DETAIL_CECO | RenderPattern.PL_DETAIL_CUENTA:
            _write_sheet(writer, df, sheet_name, title)
        case RenderPattern.SALES_INGRESOS | RenderPattern.SALES_PROYECTOS:
            df = df.rename(columns={TOTAL_COL: str(year)})
            _write_sheet(writer, df, sheet_name, title)


def _write_grouped_nota(writer, sheet_name, resolved, bs, year):
    """Write a multi-entry group on one sheet."""
    # Check if this is a sales group
    is_sales = any(e.pattern in (RenderPattern.SALES_INGRESOS, RenderPattern.SALES_PROYECTOS)
                   for _, e, _, _ in resolved)
    if is_sales:
        sales_sections = [(title, df) for _, _, title, df in resolved]
        _write_sales_details(writer, sales_sections, year, sheet_name)
        return

    # Check if all entries are BS detail (use multi-table BS layout)
    all_bs = all(e.pattern in (RenderPattern.BS_DETAIL, RenderPattern.BS_DETAIL_WITH_NIT)
                 for _, e, _, _ in resolved)
    if all_bs:
        _grouped_bs_keys = {"bs_efectivo", "bs_cxc_comerciales", "bs_cxc_otras",
                            "bs_ppe", "bs_ppe_depreciacion"}
        sections = []
        for _, entry, title, df in resolved:
            if entry.bs_key in _grouped_bs_keys:
                df = _add_pdf_category_col(df, entry.bs_key)
            sections.append((title, df, CUENTA_CONTABLE))
            # Insert NIT ranking table after this nota's cuenta table
            if entry.nit_ranking_key:
                nit_df = bs.get(entry.nit_ranking_key)
                if _has_data(nit_df):
                    nit_title = f"Top 20 por NIT - {entry.label}"
                    sections.append((nit_title, nit_df, None))
        _write_multi_table_sheet(writer, sheet_name, sections)
        return

    # Generic PL two-table or multi-table layout
    if len(resolved) == 2:
        _, _, title1, df1 = resolved[0]
        _, _, title2, df2 = resolved[1]
        _write_two_table_sheet(writer, sheet_name, title1, df1, title2, df2)
    else:
        first_title, first_df = resolved[0][2], resolved[0][3]
        _write_sheet(writer, first_df, sheet_name, first_title)
        ws = writer.sheets[sheet_name]
        label_row = HEADER_ROW + len(first_df) + EXPANDED_GAP_ROWS + 1
        for _, _, title, df in resolved[1:]:
            label_row = _write_table_block(ws, sheet_name, writer, label_row, title, df)


# ── Main export ──────────────────────────────────────────────────────────────

def export_to_excel(output, year, data: PnLReportData):
    """Write the full multi-sheet Excel workbook (P&L, BS, details, validators).

    Sheet order is driven by NOTA_GROUPS in nota_config.py.
    """
    bs = data.bs_sheets
    has_bs = _has_data(bs.get("bs_summary"))

    def _excel_has_data(entry):
        if entry.is_bs:
            return has_bs and _has_data(bs.get(entry.bs_key))
        return _has_data(getattr(data, entry.data_attr, None))

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        # ── Pre-nota sheets ───────────────────────────────────────────────
        _write_sheet(writer, data.pl_summary, "PL", "ESTADO DE RESULTADOS")
        if has_bs:
            _write_sheet(writer, bs["bs_summary"], "BS", "ESTADO DE SITUACION FINANCIERA")

        # ── Nota sheets (config-driven) ──────────────────────────────────
        sales_sheet = None

        for group, numbered_entries in numbered_groups(_excel_has_data):
            resolved = [(num, entry, nota_title(num, entry.label),
                         _resolve_excel_df(entry, data))
                        for num, entry in numbered_entries]

            first_num = resolved[0][0]
            sheet_name = f"Nota {first_num:02d}"

            if len(resolved) == 1:
                num, entry, title, df = resolved[0]
                _write_single_nota(writer, sheet_name, title, entry, df, bs, year)
            else:
                _write_grouped_nota(writer, sheet_name, resolved, bs, year)

            # Track sales sheet for styling
            if any(e.pattern in (RenderPattern.SALES_INGRESOS, RenderPattern.SALES_PROYECTOS)
                   for _, e, _, _ in resolved):
                sales_sheet = sheet_name

        # ── Post-nota sheets ─────────────────────────────────────────────
        _write_detalle_cc_x_cc(writer, data)

        _write_sheet(writer, data.detail_by_cuenta, "VALIDADOR1", "DETALLE POR CUENTA CONTABLE")
        _write_sheet(writer, data.detail_by_ceco, "VALIDADOR2", "DETALLE POR CENTRO DE COSTO")
        _write_sheet(writer, data.detail_by_ceco_cuenta, "VALIDADOR3", "DETALLE POR CENTRO DE COSTO Y CUENTA CONTABLE")
        if _has_data(bs.get("bs_validador")):
            _write_sheet(writer, bs["bs_validador"], "VALIDADOR_BS", "DETALLE BS POR CUENTA CONTABLE")

        # ── Styling ──────────────────────────────────────────────────────
        nota_sheet_names = [sn for sn in writer.sheets if sn.startswith("Nota ")]

        style_init(writer.sheets["PL"], COL_B_WIDTH_PL)
        if has_bs:
            style_init(writer.sheets["BS"], COL_B_WIDTH_BS)
        for sn in nota_sheet_names:
            style_init(writer.sheets[sn])
        style_init(writer.sheets["DETALLE_CC_x_CC"])

        style_init(writer.sheets["VALIDADOR1"])
        style_init(writer.sheets["VALIDADOR2"])
        style_init(writer.sheets["VALIDADOR3"])
        if _has_data(bs.get("bs_validador")):
            style_init(writer.sheets["VALIDADOR_BS"])

        for sn in nota_sheet_names:
            style_two_table_sheet(writer.sheets[sn])

        apply_number_format(writer)
        highlight_excluded_rows(writer, data.excluded_cuentas, "VALIDADOR1")
        style_validator_sheets(writer)
        style_pl_sheet(writer)
        format_subtotal_rows(writer, "PL", PL_SUBTOTAL_LABELS)
        if has_bs:
            style_bs_sheet(writer)
            format_bs_partida_rows(writer)
            format_subtotal_rows(writer, "BS", BS_SUBTOTAL_LABELS)

        style_detalle_cc_x_cc(writer)
        if sales_sheet and sales_sheet in writer.sheets:
            style_sales_details(writer, sales_sheet)
        if has_bs and "VALIDADOR_BS" in writer.sheets:
            style_sheet(writer.sheets["VALIDADOR_BS"], "standard_raw")
            highlight_undefined_bs_rows(
                writer.sheets["VALIDADOR_BS"],
                bs.get("bs_undefined_cuentas", set()),
            )

        validator_sheets = ["VALIDADOR1", "VALIDADOR2", "VALIDADOR3"]
        if _has_data(bs.get("bs_validador")):
            validator_sheets.append("VALIDADOR_BS")
        for sn in validator_sheets:
            writer.sheets[sn].sheet_properties.tabColor = VALIDATOR_TAB_COLOR
