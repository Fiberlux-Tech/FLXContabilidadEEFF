import calendar
import logging

import pandas as pd
from fpdf import FPDF

from models.models import PdfReportData
from accounting.rules import (
    PL_SUBTOTAL_LABELS, BS_SUBTOTAL_LABELS, BS_PARTIDA_LABELS,
    BS_EFECTIVO_GROUPS, BS_CXC_COMERCIALES_GROUPS, BS_CXC_OTRAS_GROUPS,
    BS_PPE_GROUPS, BS_PPE_DEPRECIACION_GROUPS, BS_TRIBUTOS_GROUPS,
    get_bs_group, BS_GROUP_TABLES,
)
from config.calendar import MONTH_NAMES, QUARTER_MONTHS, MONTH_NAMES_ES
from config.period import get_end_month
from config.company import COMPANY_META
from pdf.constants import (
    NAVY, CHARCOAL, WHITE, LIGHT_GRAY, MUTED_BLUE, ZEBRA_GRAY, LINE_GRAY,
    BLACK, FOOTER_GRAY,
    PAGE_MARGIN, NOTA_DESC_INDENT, TABLE_INDENT, ROW_HEIGHT, VALUE_INSET_PCT,
    HEADER_ROW_EXTRA, BLANK_ROW_SPACING, SECTION_SPACING,
    PAGE_TOP_MARGIN, HEADER_CELL_HEIGHT, SUBTITLE_CELL_HEIGHT,
    HEADER_BOTTOM_MARGIN, FOOTER_Y_OFFSET, FOOTER_CELL_HEIGHT,
    COVER_LOGO_Y, COVER_LOGO_WIDTH, COVER_LOGO_BOTTOM_GAP,
    COVER_COMPANY_CELL_H, COVER_BLOCK_Y, COVER_BLOCK_X,
    COVER_LINE_HEIGHT, COVER_BORDER_PADDING, COVER_CONTENT_TOP_PAD,
    COVER_SPACER_HEIGHT, COVER_CURRENCY_GAP, COVER_BOTTOM_BORDER_GAP,
    SUBHEADER_CELL_HEIGHT, SUBHEADER_BOTTOM_GAP,
    PL_TOP_GAP, NOTA_COL_WIDTH, LABEL_INDENT,
    _TOTAL_LABEL, _GROUP_SENTINEL, _FINAL_TOTAL_LABEL, _BS_FINAL_TOTAL_LABELS,
    PL_LABEL_PCT_NARROW, PL_LABEL_PCT_WIDE,
    DETAIL_LABEL_PCT_NARROW, DETAIL_LABEL_PCT_WIDE,
    DETAIL_2COL_LABEL_PCT_NARROW, DETAIL_2COL_LABEL_PCT_WIDE,
    MAX_NARROW_VALUE_COLS, NIT_LABEL_PCTS,
    FONT_SIZE_DATA, FONT_SIZE_HEADER, FONT_SIZE_SUBHEADER,
    FONT_SIZE_PAGE_HEADER_COMPANY, FONT_SIZE_PAGE_HEADER_TITLE,
    FONT_SIZE_SUBTITLE, FONT_SIZE_FOOTER,
    FONT_SIZE_COVER_COMPANY, FONT_SIZE_COVER_INFO, FONT_SIZE_COVER_CURRENCY,
    BORDER_TOTAL, BORDER_SUBTOTAL, BORDER_NORMAL, BORDER_COVER,
    LOGOS_DIR, _ZERO_STRINGS, _LEGAL_SUFFIX_REPLACEMENTS,
)
from config.fields import CUENTA_CONTABLE, DESCRIPCION, PARTIDA_PL, PARTIDA_BS, NIT, RAZON_SOCIAL
from pdf.renderer import _render_table, _compute_widths, _truncate_text


logger = logging.getLogger("plantillas.pdf_export")

# ---------------------------------------------------------------------------
# Named constants (previously magic numbers)
# ---------------------------------------------------------------------------
ZERO_THRESHOLD = 0.5          # Absolute-value threshold below which a number is treated as zero
UNCLASSIFIED_SORT_ORDER = 999  # Sort order for accounts not matching any known group

# ---------------------------------------------------------------------------
# Number formatting
# ---------------------------------------------------------------------------

def _is_missing(value):
    try:
        return value is None or pd.isna(value)
    except (TypeError, ValueError):
        return False


def _fmt_number(value):
    """Format a number for PDF display: 1,234,567 / (1,234,567) / —"""
    if _is_missing(value):
        return ""
    if isinstance(value, (int, float)):
        v = value
    else:
        try:
            v = float(value)
        except (TypeError, ValueError):
            return ""
    if v == 0:
        return "-"
    if v < 0:
        return f"({abs(v):,.0f})"
    return f"{v:,.0f}"


# ---------------------------------------------------------------------------
# Shared TOTAL row helpers
# ---------------------------------------------------------------------------

def _split_total_rows(df, *, check_descripcion=False):
    """Separate TOTAL rows from data rows in a DataFrame.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame with at least a CUENTA_CONTABLE column.
    check_descripcion : bool
        If True, also match rows where DESCRIPCION equals TOTAL.

    Returns
    -------
    (data_rows, total_rows) : tuple[pd.DataFrame, pd.DataFrame]
    """
    is_total = df[CUENTA_CONTABLE].astype(str).str.strip().str.upper().eq(_TOTAL_LABEL)
    if check_descripcion:
        is_total = is_total | df[DESCRIPCION].astype(str).str.strip().str.upper().eq(_TOTAL_LABEL)
    return df[~is_total].copy(), df[is_total]


# ---------------------------------------------------------------------------
# Efectivo group helpers
# ---------------------------------------------------------------------------

def _build_group_order(group_table):
    """Build an insertion-ordered {label: rank} dict from a group table.

    Appends "Sin clasificar" as the last entry so unrecognised accounts
    sort after all known groups.
    """
    seen: list[str] = []
    for _, label in group_table:
        if label not in seen:
            seen.append(label)
    order = {label: i for i, label in enumerate(seen)}
    order["Sin clasificar"] = len(seen)
    return order


def _assign_group_order(df, group_table, classify_fn):
    """Add ``_group`` and ``_group_order`` columns to *df*.

    *classify_fn* maps a CUENTA_CONTABLE string to a group label (or None).
    """
    group_order = _build_group_order(group_table)
    df = df.copy()
    df["_group"] = df[CUENTA_CONTABLE].apply(classify_fn).fillna("Sin clasificar")
    df["_group_order"] = df["_group"].map(group_order).fillna(UNCLASSIFIED_SORT_ORDER).astype(int)
    return df, group_order


def _get_efectivo_group(cuenta: str) -> str | None:
    """Return the group label for a CUENTA_CONTABLE, or None if unrecognised."""
    return get_bs_group(cuenta, BS_EFECTIVO_GROUPS)


def _inject_efectivo_groups(df: pd.DataFrame, value_cols: list[str]) -> pd.DataFrame:
    """Insert group-header rows into the efectivo detail DataFrame.

    Rows are re-sorted so that all accounts from the same group appear together
    (in the canonical group order defined by BS_EFECTIVO_GROUPS), sorted by the
    first value column descending within each group.  A group-header row is then
    inserted at the start of each group.  Group headers use a sentinel
    CUENTA_CONTABLE="__GROUP__" so the row renderer can style them distinctly.
    """
    data_rows, total_rows = _split_total_rows(df)

    data_rows, _ = _assign_group_order(
        data_rows, BS_EFECTIVO_GROUPS, _get_efectivo_group,
    )

    # Sort: group order first, then by first value col descending within group
    sort_col = value_cols[0] if value_cols else None
    sort_cols = ["_group_order", sort_col] if sort_col and sort_col in data_rows.columns else ["_group_order"]
    sort_asc = [True, False] if len(sort_cols) == 2 else [True]
    data_rows = data_rows.sort_values(sort_cols, ascending=sort_asc)

    # Build result by iterating groups: header row + group data rows
    blank_vals = {c: float("nan") for c in value_cols}
    pieces: list[pd.DataFrame] = []
    for group_label, group_df in data_rows.groupby("_group_order", sort=True):
        label = group_df["_group"].iloc[0]
        header = pd.DataFrame(
            [{CUENTA_CONTABLE: _GROUP_SENTINEL, DESCRIPCION: label, **blank_vals}],
            columns=df.columns,
        )
        pieces.append(header)
        pieces.append(group_df.drop(columns=["_group", "_group_order"]))

    combined = pd.concat(pieces, ignore_index=True) if pieces else data_rows.drop(columns=["_group", "_group_order"])

    # Re-attach TOTAL row(s)
    if not total_rows.empty:
        combined = pd.concat([combined, total_rows], ignore_index=True)
    return combined[df.columns]


def _make_row_df(rec: dict, columns, value_cols: list[str]) -> pd.DataFrame:
    """Create a single-row DataFrame with float-typed value columns."""
    row = pd.DataFrame([rec], columns=columns)
    for vc in value_cols:
        row[vc] = row[vc].astype(float)
    return row


def _aggregate_by_group(df: pd.DataFrame, value_cols: list[str],
                        group_table: list[tuple[str, str]]) -> pd.DataFrame:
    """Aggregate detail into one row per group label plus a TOTAL row.

    Individual CUENTA_CONTABLE rows are summed within each group defined by
    *group_table*.  The result has columns: CUENTA_CONTABLE (empty string),
    DESCRIPCION (group label), and all value columns.
    """
    # Strip any pre-existing TOTAL row
    data_rows, _ = _split_total_rows(df, check_descripcion=True)

    data_rows, _ = _assign_group_order(
        data_rows, group_table, lambda c: get_bs_group(c, group_table),
    )

    agg = data_rows.groupby(["_group", "_group_order"], observed=True)[value_cols].sum().reset_index()
    agg = agg.sort_values("_group_order").reset_index(drop=True)

    result_rows = []
    for _, row in agg.iterrows():
        rec = {CUENTA_CONTABLE: "", DESCRIPCION: row["_group"],
               **{vc: row[vc] for vc in value_cols}}
        result_rows.append(rec)

    result = pd.DataFrame(result_rows, columns=df.columns)
    for vc in value_cols:
        result[vc] = result[vc].astype(float)

    # Always append a computed total row (sum of all group rows)
    total_rec = {CUENTA_CONTABLE: _TOTAL_LABEL, DESCRIPCION: _TOTAL_LABEL,
                 **{vc: result[vc].sum() for vc in value_cols}}
    result = pd.concat([result, _make_row_df(total_rec, df.columns, value_cols)],
                       ignore_index=True)

    return result[df.columns]


def _aggregate_efectivo_by_group(df: pd.DataFrame, value_cols: list[str]) -> pd.DataFrame:
    """Aggregate efectivo detail into one row per group label plus a TOTAL row."""
    return _aggregate_by_group(df, value_cols, BS_EFECTIVO_GROUPS)


# ---------------------------------------------------------------------------
# DataFrame → row dicts
# ---------------------------------------------------------------------------

def _classify_row_type(labels, raw_values, *,
                       total_labels=frozenset(), final_total_labels=frozenset(),
                       subtotal_labels=frozenset()):
    """Classify a row: blank / final_total / subtotal / total / normal.

    Parameters
    ----------
    labels : list[str]
        Label values for the row.
    raw_values : list
        Numeric values for the row.
    total_labels : set[str]
        Labels matched against ANY label → "total".
    final_total_labels : set[str]
        First-label matches → "final_total".
    subtotal_labels : set[str]
        First-label matches → "subtotal".
    """
    is_blank = all(_is_missing(v) for v in raw_values) and all(l == "" for l in labels)
    if is_blank:
        return "blank"
    first_label = str(labels[0]).strip() if labels else ""
    if total_labels and any(str(l).strip() in total_labels for l in labels):
        return "total"
    if first_label in final_total_labels:
        return "final_total"
    if first_label in subtotal_labels:
        return "subtotal"
    return "normal"


def _pl_row_type(labels, raw_values):
    """Classify a PL row: blank / final_total / subtotal / total / normal."""
    return _classify_row_type(
        labels, raw_values,
        total_labels={_TOTAL_LABEL},
        final_total_labels={_FINAL_TOTAL_LABEL},
        subtotal_labels=PL_SUBTOTAL_LABELS,
    )


def _bs_row_type(labels, raw_values):
    """Classify a BS summary row: blank / final_total / total / normal."""
    return _classify_row_type(
        labels, raw_values,
        final_total_labels=_BS_FINAL_TOTAL_LABELS,
        subtotal_labels=BS_SUBTOTAL_LABELS,
    )


def _df_to_rows(df, label_cols, value_cols, *, row_type_classifier=None):
    """Convert a DataFrame to a list of row dicts for PDF rendering.

    Parameters
    ----------
    row_type_classifier : callable(labels, raw_values) -> str, optional
        Returns the row_type string for a non-sentinel row.
        Defaults to _pl_row_type (P&L classification).
    """
    if row_type_classifier is None:
        row_type_classifier = _pl_row_type

    # Pre-compute column indices for fast positional access via itertuples
    all_cols = list(df.columns)
    label_idx = [all_cols.index(c) for c in label_cols]
    value_idx = [all_cols.index(c) for c in value_cols]

    rows = []
    for tup in df.itertuples(index=False):
        labels = [
            "" if _is_missing(tup[i]) else tup[i]
            for i in label_idx
        ]
        raw_values = [tup[i] for i in value_idx]

        # Group-header sentinel injected by _inject_efectivo_groups
        if str(labels[0]).strip() == _GROUP_SENTINEL:
            group_label = str(labels[1]).strip() if len(labels) > 1 else ""
            rows.append({
                "labels": ["", group_label] if len(labels) > 1 else [group_label],
                "nums": [""] * len(value_cols),
                "row_type": "group_header",
            })
            continue

        row_type = row_type_classifier(labels, raw_values)
        rows.append({
            "labels": labels,
            "nums": [_fmt_number(v) for v in raw_values],
            "row_type": row_type,
        })
    return rows


def _df_to_rows_bs(df, label_cols, value_cols):
    """Convert a BS summary DataFrame to row dicts (BS row-type classification)."""
    return _df_to_rows(df, label_cols, value_cols, row_type_classifier=_bs_row_type)



def _filter_zero_rows(rows):
    """Remove normal rows where all formatted values are effectively zero.

    Catches '-' (exact zero), '' (missing), '0', and '(0)' (values that
    round to zero after formatting).
    """
    return [
        r for r in rows
        if r["row_type"] != "normal" or any(n not in _ZERO_STRINGS for n in r["nums"])
    ]


def _remove_orphaned_group_headers(rows):
    """Remove group_header rows that have no normal data rows immediately following them.

    A group_header is orphaned when every row in its group was removed (e.g. by
    _filter_zero_rows), leaving the header followed directly by another
    group_header, a total/subtotal, a blank, or the end of the list.
    """
    result = []
    for i, row in enumerate(rows):
        if row["row_type"] == "group_header":
            has_data = False
            for j in range(i + 1, len(rows)):
                rt = rows[j]["row_type"]
                if rt == "normal":
                    has_data = True
                    break
                if rt in ("group_header", "total"):
                    break
            if not has_data:
                continue
        result.append(row)
    return result


def _drop_zero_rows(rows):
    """Filter zero-value normal rows then remove any newly orphaned group headers."""
    return _remove_orphaned_group_headers(_filter_zero_rows(rows))


# ---------------------------------------------------------------------------
# Period labels
# ---------------------------------------------------------------------------

def _build_period_label(data):
    if data.period_type == "month":
        return f"{MONTH_NAMES_ES[data.period_num]} {data.year}"
    elif data.period_type == "quarter":
        end_month = get_end_month(data.period_type, data.period_num)
        return f"Q{data.period_num} {data.year} (Enero - {MONTH_NAMES_ES[end_month]})"
    else:
        return f"Acumulado {data.year}"


def _build_cover_date(data):
    end_month = get_end_month(data.period_type, data.period_num)
    day = calendar.monthrange(data.year, end_month)[1]
    month_name = MONTH_NAMES_ES[end_month].upper()
    return f"AL {day} DE {month_name} DE {data.year}"


def _build_header_subtitle(data):
    """Return the period subtitle line shown below the statement title in page headers."""
    year = data.year
    prev_year = year - 1
    if data.period_type == "year":
        return (
            f"Por los años terminados el 31 de diciembre de {year} y de {prev_year}, "
            f"cifras no auditadas."
        )
    elif data.period_type == "quarter":
        end_month = get_end_month(data.period_type, data.period_num)
        day = calendar.monthrange(year, end_month)[1]
        month_name = MONTH_NAMES_ES[end_month]
        q = data.period_num
        return (
            f"Trimestre {q} al {day} de {month_name} del {year} y del {prev_year}, "
            f"cifras no auditadas."
        )
    else:  # month
        end_month = get_end_month(data.period_type, data.period_num)
        month_name = MONTH_NAMES_ES[end_month]
        return f"Al 31 de {month_name} de {year} y de {prev_year}. Cifras no auditadas."


# ---------------------------------------------------------------------------
# Custom PDF class
# ---------------------------------------------------------------------------

class FinancialPDF(FPDF):

    def __init__(self):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_margins(PAGE_MARGIN, PAGE_TOP_MARGIN, PAGE_MARGIN)
        self.set_auto_page_break(auto=True, margin=PAGE_MARGIN)
        self.is_cover = True   # First page is always the cover
        self.company_name = ""
        self.page_title = ""
        self.page_subtitle = ""            # dynamic subtitle; empty = no subtitle line
        self.show_company_in_header = True # False = single-line header (notes continuations)

    def header(self):
        if self.is_cover:
            return
        self.set_x(self.l_margin)
        # Line 1: Company name (bold, smaller) — omitted for notes continuation pages
        if self.show_company_in_header:
            self._set_navy_bold(FONT_SIZE_PAGE_HEADER_COMPANY)
            self.cell(0, HEADER_CELL_HEIGHT, self.company_name.upper(), align="L", new_x="LMARGIN", new_y="NEXT")
            self.ln(HEADER_CELL_HEIGHT)
        # Line 2: Statement title (not bold, larger)
        self._set_charcoal(FONT_SIZE_PAGE_HEADER_TITLE)
        self.cell(0, HEADER_CELL_HEIGHT, self.page_title, align="L", new_x="LMARGIN", new_y="NEXT")
        # Line 3: Period subtitle (regular, smaller) — omitted when empty
        if self.page_subtitle:
            self.ln(HEADER_CELL_HEIGHT / 2)
            self._set_charcoal(FONT_SIZE_SUBTITLE)
            self.cell(0, SUBTITLE_CELL_HEIGHT, self.page_subtitle, align="L", new_x="LMARGIN", new_y="NEXT")
        self.ln(HEADER_BOTTOM_MARGIN)

    # --- Reusable style setters ---

    def _set_navy_bold(self, size):
        self.set_font("Helvetica", "B", size)
        self.set_text_color(*NAVY)

    def _set_charcoal(self, size, style=""):
        self.set_font("Helvetica", style, size)
        self.set_text_color(*CHARCOAL)

    def footer(self):
        self.set_y(FOOTER_Y_OFFSET)
        self.set_font("Helvetica", "", FONT_SIZE_FOOTER)
        self.set_text_color(*FOOTER_GRAY)
        self.cell(0, FOOTER_CELL_HEIGHT, "Confidencial", align="L")
        self.cell(0, FOOTER_CELL_HEIGHT, f"Pagina {self.page_no()} de {{nb}}", align="R")


# ---------------------------------------------------------------------------
# Cover page
# ---------------------------------------------------------------------------

def _render_cover(pdf: FinancialPDF, data: PdfReportData):
    meta = COMPANY_META.get(data.company, {})
    legal_name = meta.get("legal_name", data.company)
    ruc = meta.get("ruc", "")
    cover_date = _build_cover_date(data)

    pdf.add_page()
    page_w = pdf.w  # 210mm

    # --- Logo (if exists) ---
    logo_path = None
    for ext in ("png", "jpg", "jpeg"):
        candidate = LOGOS_DIR / f"{data.company}.{ext}"
        if candidate.exists():
            logo_path = str(candidate)
            break

    y_cursor = COVER_LOGO_Y

    if logo_path:
        pdf.image(logo_path, x=(page_w - COVER_LOGO_WIDTH) / 2, y=y_cursor, w=COVER_LOGO_WIDTH)
        y_cursor += COVER_LOGO_BOTTOM_GAP

    # --- Company name (centered) ---
    pdf.set_y(y_cursor)
    pdf._set_navy_bold(FONT_SIZE_COVER_COMPANY)
    pdf.cell(0, COVER_COMPANY_CELL_H, data.company.upper(), align="C", new_x="LMARGIN", new_y="NEXT")

    # --- Info block (left-aligned, vertically centered area) ---
    block_y = COVER_BLOCK_Y
    block_x = COVER_BLOCK_X

    # Calculate border width based on longest line
    pdf._set_navy_bold(FONT_SIZE_COVER_INFO)
    lines = [
        legal_name.upper(),
        f"RUC {ruc}",
        "",
        "ESTADOS FINANCIEROS",
        cover_date,
    ]
    max_text_w = 0
    for line in lines:
        w = pdf.get_string_width(line)
        if w > max_text_w:
            max_text_w = w
    # Add padding for the currency line (italic, slightly different)
    pdf._set_charcoal(FONT_SIZE_COVER_CURRENCY, "I")
    currency_w = pdf.get_string_width("(Expresado en Soles)")
    if currency_w > max_text_w:
        max_text_w = currency_w

    border_w = max_text_w + COVER_BORDER_PADDING
    line_h = COVER_LINE_HEIGHT

    # Top border
    pdf.set_draw_color(*NAVY)
    pdf.set_line_width(BORDER_COVER)
    pdf.line(block_x, block_y, block_x + border_w, block_y)

    # Content
    content_y = block_y + COVER_CONTENT_TOP_PAD

    # Legal name
    pdf.set_xy(block_x, content_y)
    pdf._set_navy_bold(FONT_SIZE_COVER_INFO)
    pdf.cell(border_w, line_h, legal_name.upper(), new_x="LMARGIN", new_y="NEXT")

    # RUC
    pdf.set_x(block_x)
    pdf._set_charcoal(FONT_SIZE_COVER_INFO)
    pdf.cell(border_w, line_h, f"RUC {ruc}", new_x="LMARGIN", new_y="NEXT")

    # Spacer
    pdf.set_x(block_x)
    pdf.cell(border_w, COVER_SPACER_HEIGHT, "", new_x="LMARGIN", new_y="NEXT")

    # Report name
    pdf.set_x(block_x)
    pdf._set_navy_bold(FONT_SIZE_COVER_INFO)
    pdf.cell(border_w, line_h, "ESTADOS FINANCIEROS", new_x="LMARGIN", new_y="NEXT")

    # Date
    pdf.set_x(block_x)
    pdf._set_charcoal(FONT_SIZE_COVER_INFO)
    pdf.cell(border_w, line_h, cover_date, new_x="LMARGIN", new_y="NEXT")

    # Currency note
    pdf.set_x(block_x)
    pdf.ln(COVER_CURRENCY_GAP)
    pdf.set_x(block_x)
    pdf._set_charcoal(FONT_SIZE_COVER_CURRENCY, "I")
    pdf.cell(border_w, line_h, "(Expresado en Soles)", new_x="LMARGIN", new_y="NEXT")

    # Bottom border
    bottom_y = pdf.get_y() + COVER_BOTTOM_BORDER_GAP
    pdf.line(block_x, bottom_y, block_x + border_w, bottom_y)


# ---------------------------------------------------------------------------
# Section title
# ---------------------------------------------------------------------------

def _render_subheader(pdf: FinancialPDF, text: str):
    """Render a note subheader like 'Nota 01. Ingresos Ordinarios'."""
    pdf._set_navy_bold(FONT_SIZE_SUBHEADER)
    pdf.cell(0, SUBHEADER_CELL_HEIGHT, text, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(SUBHEADER_BOTTOM_GAP)
    pdf.set_x(pdf.l_margin + NOTA_DESC_INDENT)
    pdf.set_font("Helvetica", "", FONT_SIZE_DATA)
    pdf.set_text_color(*CHARCOAL)
    pdf.cell(0, SUBHEADER_CELL_HEIGHT, "a) El rubro está constituido del siguiente modo:",
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*BLACK)
    pdf.ln(SUBHEADER_BOTTOM_GAP)


def _render_description_line(pdf: FinancialPDF, text: str):
    """Render a single indented description line (e.g. 'b) ...')."""
    pdf.set_x(pdf.l_margin + NOTA_DESC_INDENT)
    pdf.set_font("Helvetica", "", FONT_SIZE_DATA)
    pdf.set_text_color(*CHARCOAL)
    pdf.cell(0, SUBHEADER_CELL_HEIGHT, text,
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*BLACK)
    pdf.ln(SUBHEADER_BOTTOM_GAP)


def _render_nit_ranking_description(pdf: FinancialPDF):
    """Render the 'b) La cuenta tiene como principales participantes a:' line."""
    _render_description_line(pdf, "b) La cuenta tiene como principales participantes a:")





# ---------------------------------------------------------------------------
# NIT pivot table renderer
# ---------------------------------------------------------------------------

def _shorten_nit_header(col_name):
    """Shorten an account-description column name for the NIT pivot header.

    Examples:
        OTRAS CUENTAS POR COBRAR DIV. REL. MN  → CxC OTRAS DIV. MN
        CUENTAS POR COBRAR NO EMITIDAS REL. ME  → CxC NO EMITIDAS ME
        CUENTAS POR COBRAR EMITIDAS EN CARTERA REL. → CxC EMITIDAS EN CARTERA
        FACTURAS NO EMITIDAS POR PAGAR RELACIONADAS MN → CxP NO EMITIDAS MN
    """
    if col_name == _TOTAL_LABEL:
        return col_name
    s = col_name
    # Replace core phrases with short prefix
    for long, short in (
        ("OTRAS CUENTAS POR COBRAR", "CXC OTRAS"),
        ("CUENTAS POR COBRAR",       "CXC"),
        ("FACTURAS NO EMITIDAS POR PAGAR", "CXP NO EMITIDAS"),
        ("OTRAS CUENTAS POR PAGAR",  "CXP OTRAS"),
        ("CUENTAS POR PAGAR",        "CXP"),
    ):
        if long in s.upper():
            s = short + s[s.upper().index(long) + len(long):]
            break
    # Strip "REL." / "RELACIONADAS" noise
    for noise in (" REL.", " RELACIONADAS"):
        s = s.replace(noise, "")
    # Collapse extra whitespace
    s = " ".join(s.split())
    return s



def _abbreviate_legal_suffix(s):
    """Replace full Peruvian legal-entity suffixes with their abbreviations."""
    if not isinstance(s, str):
        return s
    upper = s.upper()
    for long_form, short_form in _LEGAL_SUFFIX_REPLACEMENTS:
        if long_form in upper:
            # Find position in the original string (case-insensitive) and replace
            idx = upper.find(long_form)
            s = s[:idx] + short_form + s[idx + len(long_form):]
            break  # only one suffix per name
    return s.strip()


def _render_nit_pivot(pdf: FinancialPDF, nit_df, year_label, *,
                      description: str | None = None, drop_nit_col: bool = False):
    """Render a NIT pivot table with a description line above it.

    *nit_df* has columns: NIT, RAZON_SOCIAL, <account descriptions...>, TOTAL.

    Parameters
    ----------
    description : str or None
        If given, render this text as a description line instead of the
        default year subheader + "a) El rubro está constituido...".
    drop_nit_col : bool
        If True, drop the NIT column and render only RAZON_SOCIAL as label.
    """
    if nit_df.empty:
        return

    # Truncate RAZON_SOCIAL at " - " to remove duplicate abbreviated names
    razon = nit_df[RAZON_SOCIAL].apply(
        lambda s: s.split(" - ")[0].strip() if isinstance(s, str) and " - " in s else s
    )
    # Abbreviate common Peruvian legal suffixes (longest first to avoid
    # partial matches, e.g. "SOCIEDAD ANONIMA CERRADA" before "SOCIEDAD ANONIMA")
    razon = razon.apply(_abbreviate_legal_suffix)
    nit_df = nit_df.assign(**{RAZON_SOCIAL: razon})

    value_cols = [c for c in nit_df.columns if c not in (NIT, RAZON_SOCIAL)]

    # Drop value columns whose total is zero (TOTAL row is last)
    keep_cols = [c for c in value_cols if c == _TOTAL_LABEL or nit_df[c].abs().sum() > ZERO_THRESHOLD]
    # Recalculate TOTAL after dropping columns if TOTAL exists
    data_cols = [c for c in keep_cols if c != _TOTAL_LABEL]
    if not data_cols:
        return
    if _TOTAL_LABEL in keep_cols:
        nit_df = nit_df.assign(**{_TOTAL_LABEL: nit_df[data_cols].sum(axis=1)})
    value_cols = keep_cols
    nit_df = nit_df[[NIT, RAZON_SOCIAL] + value_cols]

    # Drop rows where all value columns are zero (except TOTAL row)
    is_total = nit_df[RAZON_SOCIAL].eq(_TOTAL_LABEL)
    zero_mask = nit_df[value_cols].abs().sum(axis=1) <= ZERO_THRESHOLD
    nit_df = nit_df[~(zero_mask & ~is_total)].reset_index(drop=True)

    display_headers = [_shorten_nit_header(c) for c in value_cols]

    if drop_nit_col:
        nit_df = nit_df.drop(columns=[NIT])
        label_cols = [RAZON_SOCIAL]
        header_labels = ["RAZON SOCIAL"]
        label_pcts = [sum(NIT_LABEL_PCTS)]
    else:
        label_cols = [NIT, RAZON_SOCIAL]
        header_labels = ["NIT", "RAZON SOCIAL"]
        label_pcts = NIT_LABEL_PCTS

    n_val = len(value_cols)
    label_widths, val_w = _compute_widths(pdf, n_val, label_pcts)

    rows = _df_to_rows(nit_df, label_cols, value_cols)
    rows = _drop_zero_rows(rows)
    if not rows:
        return

    # Description or year subheader
    if description is not None:
        _render_description_line(pdf, description)
    else:
        _render_subheader(pdf, str(year_label))

    _render_table(pdf, rows, header_labels, display_headers,
                  label_widths, val_w, alternating=True, wrap_headers=True)


# ---------------------------------------------------------------------------
# Compute column widths
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Main export function
# ---------------------------------------------------------------------------

def _render_pl_summary(pdf, data, col_names, n_vals, pl_label_pcts, subtitle_text, nota_map):
    """Render the P&L summary page."""
    pl_df = data.pl_summary.copy()
    pl_df["NOTA"] = pl_df[PARTIDA_PL].map(nota_map).fillna("-")
    pl_df.loc[pl_df[PARTIDA_PL].str.strip() == "", "NOTA"] = ""
    pl_rows = _df_to_rows(pl_df, [PARTIDA_PL, "NOTA"], col_names)

    pdf.page_title = "Estado de Resultados"
    pdf.page_subtitle = subtitle_text
    pdf.show_company_in_header = True
    pdf.add_page()
    pdf.ln(PL_TOP_GAP)

    pl_widths, pl_val_w = _compute_widths(pdf, n_vals, pl_label_pcts)
    pl_nota_widths = [pl_widths[0] - NOTA_COL_WIDTH, NOTA_COL_WIDTH]
    _render_table(pdf, pl_rows, ["", "Nota"], col_names, pl_nota_widths, pl_val_w,
                  label_aligns=["L", "C"])


def _render_bs_summary(pdf, data, bs_col_names, n_bs_vals, subtitle_text, nota_map):
    """Render the Balance Sheet summary page."""
    bs_label_pcts = PL_LABEL_PCT_NARROW if n_bs_vals <= MAX_NARROW_VALUE_COLS else PL_LABEL_PCT_WIDE
    bs_widths, bs_val_w = _compute_widths(pdf, n_bs_vals, bs_label_pcts)

    bs_df = data.bs_summary.copy()
    bs_df["NOTA"] = bs_df[PARTIDA_BS].map(nota_map).fillna("-")
    bs_df.loc[bs_df[PARTIDA_BS].str.strip() == "", "NOTA"] = ""
    bs_rows = _df_to_rows_bs(bs_df, [PARTIDA_BS, "NOTA"], bs_col_names)

    pdf.page_title = "Balance General"
    pdf.page_subtitle = subtitle_text
    pdf.show_company_in_header = True
    pdf.add_page()
    pdf.ln(PL_TOP_GAP)

    bs_nota_widths = [bs_widths[0] - NOTA_COL_WIDTH, NOTA_COL_WIDTH]
    _render_table(pdf, bs_rows, ["", "Nota"], bs_col_names, bs_nota_widths, bs_val_w,
                  alternating=True, label_aligns=["L", "C"])


def _render_nota_bs_entry(pdf, entry, data, bs_col_names, n_bs_vals, bs_det_widths, bs_det_val_w):
    """Render a single BS nota entry: detail table + optional NIT ranking/pivot."""
    from config.nota import RenderPattern

    bs_df = data.bs_details.get(entry.bs_key)
    if bs_df is None:
        logger.warning("BS detail key '%s' not found in data — skipping nota.", entry.bs_key)
        return
    # Grouped BS sections: aggregate by prefix-group, single DESCRIPCION column
    group_table = BS_GROUP_TABLES.get(entry.bs_key)
    if group_table is not None:
        bs_df = _aggregate_by_group(bs_df, bs_col_names, group_table)
        label_cols = [DESCRIPCION]
        header_labels = [DESCRIPCION]
        eff_widths = [sum(bs_det_widths)]
    else:
        label_cols = list(entry.pdf_label_cols)
        header_labels = list(entry.pdf_header_labels)
        eff_widths = bs_det_widths

    r = _drop_zero_rows(_df_to_rows(bs_df, label_cols, bs_col_names))
    _render_table(pdf, r, header_labels, bs_col_names,
                  eff_widths, bs_det_val_w, alternating=True)

    # Top-N NIT ranking table (without NIT column)
    if entry.nit_ranking_key and entry.nit_ranking_key in data.nit_rankings:
        nit_rank_df = data.nit_rankings[entry.nit_ranking_key]
        if not nit_rank_df.empty:
            pdf.ln(SECTION_SPACING / 2)
            _render_nit_ranking_description(pdf)
            nit_rank_widths, nit_rank_val_w = _compute_widths(
                pdf, n_bs_vals, [sum(NIT_LABEL_PCTS)],
            )
            pdf.set_font("Helvetica", "", FONT_SIZE_DATA)
            col_w = nit_rank_widths[0] - LABEL_INDENT
            nit_rank_df = nit_rank_df.assign(**{
                RAZON_SOCIAL: nit_rank_df[RAZON_SOCIAL].apply(
                    lambda s: _truncate_text(pdf, s, col_w) if isinstance(s, str) else s
                )
            })
            nit_rows = _drop_zero_rows(
                _df_to_rows(nit_rank_df, [RAZON_SOCIAL], bs_col_names)
            )
            if nit_rows:
                _render_table(pdf, nit_rows, ["RAZON SOCIAL"], bs_col_names,
                              nit_rank_widths, nit_rank_val_w, alternating=True)

    # NIT pivot tables for relacionadas (one per year)
    if (entry.pattern == RenderPattern.BS_DETAIL_WITH_NIT
            and entry.nit_pivot_key
            and entry.nit_pivot_key in data.nit_pivots):
        nit_cur, nit_prev = data.nit_pivots[entry.nit_pivot_key]
        pdf.ln(SECTION_SPACING)
        _render_nit_pivot(
            pdf, nit_cur, data.year,
            description=f"b) Durante el {data.year} la composición fue la siguiente:",
            drop_nit_col=True,
        )
        pdf.ln(SECTION_SPACING)
        _render_nit_pivot(
            pdf, nit_prev, data.year - 1,
            description=f"b) Durante el {data.year - 1} la composición fue la siguiente:",
            drop_nit_col=True,
        )


def _render_notes(pdf, data, col_names, n_vals, bs_col_names, n_bs_vals,
                  detail_label_pcts, detail_2col_label_pcts,
                  subtitle_text, pl_row_cache, _pdf_has_data):
    """Render all nota pages (config-driven)."""
    from config.nota_utils import numbered_groups, nota_title as _nota_title

    bs_det_label_pcts = DETAIL_LABEL_PCT_NARROW if n_bs_vals <= MAX_NARROW_VALUE_COLS else DETAIL_LABEL_PCT_WIDE
    bs_det_widths, bs_det_val_w = _compute_widths(pdf, n_bs_vals, bs_det_label_pcts)
    det_widths, det_val_w = _compute_widths(pdf, n_vals, detail_label_pcts)
    det_2col_widths, det_2col_val_w = _compute_widths(pdf, n_vals, detail_2col_label_pcts)

    first_group = True
    for group, numbered_entries in numbered_groups(_pdf_has_data):
        if first_group:
            pdf.page_title = "Notas a los estados financieros"
            pdf.page_subtitle = subtitle_text
            pdf.show_company_in_header = True
            first_group = False
        pdf.add_page()
        # Continuation pages get a shorter header
        pdf.page_title = "Notas a los estados financieros (continuación)"
        pdf.page_subtitle = ""
        pdf.show_company_in_header = False

        for i, (num, entry) in enumerate(numbered_entries):
            if i > 0:
                pdf.ln(SECTION_SPACING)

            _render_subheader(pdf, _nota_title(num, entry.label))

            if entry.is_bs:
                _render_nota_bs_entry(pdf, entry, data, bs_col_names, n_bs_vals,
                                      bs_det_widths, bs_det_val_w)
            else:
                r = pl_row_cache[entry.data_attr]
                hdrs = list(entry.pdf_header_labels)
                if len(hdrs) >= 2:
                    ew, evw = det_2col_widths, det_2col_val_w
                else:
                    ew, evw = det_widths, det_val_w
                _render_table(pdf, r, hdrs, col_names, ew, evw)


def export_to_pdf(output_path, data: PdfReportData):
    """Render the PDF report using fpdf2."""

    pdf = FinancialPDF()
    pdf.alias_nb_pages()

    col_names = list(data.column_names)
    n_vals = len(col_names)

    # Width proportions
    if n_vals <= MAX_NARROW_VALUE_COLS:
        pl_label_pcts = PL_LABEL_PCT_NARROW
        detail_label_pcts = DETAIL_LABEL_PCT_NARROW
        detail_2col_label_pcts = DETAIL_2COL_LABEL_PCT_NARROW
    else:
        pl_label_pcts = PL_LABEL_PCT_WIDE
        detail_label_pcts = DETAIL_LABEL_PCT_WIDE
        detail_2col_label_pcts = DETAIL_2COL_LABEL_PCT_WIDE

    subtitle_text = _build_header_subtitle(data)

    # Store company name for page headers
    meta = COMPANY_META.get(data.company, {})
    pdf.company_name = meta.get("legal_name", data.company)

    # ===== Page 1: Cover =====
    _render_cover(pdf, data)
    pdf.is_cover = False
    pdf.set_left_margin(PAGE_MARGIN)
    pdf.set_right_margin(PAGE_MARGIN)

    # ===== Prepare nota data (needed before summary pages for nota references) =====
    from pdf.reports import build_bs_column_names
    bs_col_names = list(build_bs_column_names(data.year))
    n_bs_vals = len(bs_col_names)

    # Pre-convert PL DataFrames to row dicts
    pl_row_cache = {}
    _PL_ATTRS = [
        "sales_details", "proyectos_especiales",
        "costo", "gasto_venta",
        "gasto_admin", "resultado_financiero_ingresos", "resultado_financiero_gastos",
        "diferencia_cambio_ingresos", "diferencia_cambio_gastos",
        "dya_costo", "dya_gasto",
    ]
    from config.nota import NOTA_GROUPS
    from config.nota_utils import build_partida_nota_map
    _attr_label_cols = {
        e.data_attr: list(e.pdf_label_cols)
        for grp in NOTA_GROUPS for e in grp.entries
    }
    for attr in _PL_ATTRS:
        df = getattr(data, attr, None)
        if df is not None and not df.empty:
            label_cols = _attr_label_cols.get(attr, [DESCRIPCION])
            r = _df_to_rows(df, label_cols, col_names)
            pl_row_cache[attr] = _drop_zero_rows(r)

    def _pdf_has_data(entry):
        if entry.is_bs:
            df = data.bs_details.get(entry.bs_key)
            if df is None or df.empty:
                return False
            r = _drop_zero_rows(
                _df_to_rows(df, list(entry.pdf_label_cols), bs_col_names)
            )
            return bool(r)
        return bool(pl_row_cache.get(entry.data_attr))

    nota_map = build_partida_nota_map(_pdf_has_data)

    # ===== Page 2: PL Summary =====
    _render_pl_summary(pdf, data, col_names, n_vals, pl_label_pcts, subtitle_text, nota_map)

    # ===== Page 3: Balance Sheet =====
    _render_bs_summary(pdf, data, bs_col_names, n_bs_vals, subtitle_text, nota_map)

    # ===== Notes =====
    _render_notes(pdf, data, col_names, n_vals, bs_col_names, n_bs_vals,
                  detail_label_pcts, detail_2col_label_pcts,
                  subtitle_text, pl_row_cache, _pdf_has_data)

    # ===== Write =====
    pdf.output(str(output_path))
    logger.info("PDF saved to %s", output_path)
