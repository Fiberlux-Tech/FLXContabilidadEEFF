"""PDF table rendering — headers, data rows, bold rows, and table layout."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pdf.constants import (
    BLACK, CHARCOAL, LABEL_INDENT, TABLE_INDENT, ROW_HEIGHT, VALUE_INSET_PCT,
    HEADER_ROW_EXTRA, BLANK_ROW_SPACING, PAGE_MARGIN,
    FONT_SIZE_DATA, FONT_SIZE_HEADER,
    BORDER_TOTAL, BORDER_SUBTOTAL,
)

if TYPE_CHECKING:
    from pdf.export import FinancialPDF



# ---------------------------------------------------------------------------
# Table header renderers
# ---------------------------------------------------------------------------

def _render_table_header(pdf: FinancialPDF, all_headers, all_widths, n_label_cols, row_h,
                         inset=0, inner_w=0, label_aligns=None):
    """Render the header row for a data table: bold black text.

    Value column headers are rendered as two rows: the year label on top
    and "S/" centered below it (matching standard financial statement style).
    """
    line_h = row_h + HEADER_ROW_EXTRA
    header_h = line_h * 2  # two rows: year + currency
    y_start = pdf.get_y()
    x_start = pdf.l_margin + TABLE_INDENT
    pdf.set_text_color(*BLACK)
    pdf.set_font("Helvetica", "B", FONT_SIZE_HEADER)

    # Row 1: label headers (vertically centred) + year text (right-aligned like numbers)
    x_cursor = x_start
    for i, header in enumerate(all_headers):
        if i >= n_label_cols:
            # Year text — right-aligned within the same inset zone as data numbers
            pdf.set_xy(x_cursor + inset, y_start)
            pdf.cell(inner_w, line_h, header, border=0, align="R")
        else:
            # Label column header — vertically centred across both rows
            align = label_aligns[i] if label_aligns and i < len(label_aligns) else "L"
            x_off = LABEL_INDENT if i == 0 and align == "L" else 0
            pdf.set_xy(x_cursor + x_off, y_start + line_h / 2)
            pdf.cell(all_widths[i] - x_off, line_h, header, border=0, fill=False, align=align)
        x_cursor += all_widths[i]

    # Row 2: "S/" right-aligned under each value column (same zone as numbers)
    x_cursor = x_start
    for i in range(len(all_headers)):
        if i >= n_label_cols:
            pdf.set_xy(x_cursor + inset, y_start + line_h)
            pdf.cell(inner_w, line_h, "S/", border=0, align="R")
        x_cursor += all_widths[i]

    pdf.set_xy(x_start, y_start + header_h)


def _wrap_text(pdf, text, max_w):
    """Split *text* into lines that each fit within *max_w* mm."""
    if not text or pdf.get_string_width(text) <= max_w:
        return [text or ""]
    words = text.split()
    lines, cur = [], ""
    for word in words:
        test = (cur + " " + word).strip()
        if pdf.get_string_width(test) > max_w and cur:
            lines.append(cur)
            cur = word
        else:
            cur = test
    if cur:
        lines.append(cur)
    return lines or [text]


def _truncate_text(pdf: FinancialPDF, text: str, max_w: float,
                   ellipsis: str = "...") -> str:
    """Truncate *text* so it fits within *max_w* mm, appending *ellipsis* if cut."""
    if not text or pdf.get_string_width(text) <= max_w:
        return text or ""
    ell_w = pdf.get_string_width(ellipsis)
    target = max_w - ell_w
    if target <= 0:
        return ellipsis
    # Binary-ish trim: shorten from the end until it fits
    for end in range(len(text), 0, -1):
        if pdf.get_string_width(text[:end]) <= target:
            return text[:end].rstrip() + ellipsis
    return ellipsis


def _render_wrapped_header(pdf, all_headers, all_widths, n_label_cols, row_h,
                           inset=0, inner_w=0):
    """Render a header row with text wrapping for both label and value columns.

    Value columns wrap their description text across multiple lines,
    with "S/" as the final row beneath.
    """
    line_h = row_h       # height per text line inside the header
    pdf.set_font("Helvetica", "B", FONT_SIZE_HEADER)

    # 1) Measure how many lines each header needs
    #    Label columns: wrap to fit column width
    #    Value columns: wrap to fit inner width, plus 1 extra line for "S/"
    max_lines = 2  # minimum: at least year + S/ for value columns
    for i, header in enumerate(all_headers):
        if i >= n_label_cols:
            eff_w = (inner_w if inner_w > 0 else all_widths[i]) - 1
            n_lines = len(_wrap_text(pdf, header, eff_w)) + 1  # +1 for "S/"
        else:
            w = all_widths[i]
            n_lines = len(_wrap_text(pdf, header, w - 1))
        if n_lines > max_lines:
            max_lines = n_lines

    header_h = max_lines * line_h + HEADER_ROW_EXTRA
    y_start = pdf.get_y()
    x_start = pdf.get_x()

    pdf.set_text_color(*BLACK)
    x_cursor = x_start
    for i, header in enumerate(all_headers):
        w = all_widths[i]
        if i >= n_label_cols:
            # Value column: wrap description text + "S/" at the bottom
            eff_inset = inset if inner_w > 0 else 0
            eff_w = inner_w if inner_w > 0 else w
            lines = _wrap_text(pdf, header, eff_w - 1)
            # Total block = wrapped lines + "S/" line, centred vertically
            block_lines = len(lines) + 1
            block_h = block_lines * line_h
            val_top = y_start + (header_h - block_h) / 2
            for j, ln_text in enumerate(lines):
                pdf.set_xy(x_cursor + eff_inset, val_top + j * line_h)
                pdf.cell(eff_w, line_h, ln_text, border=0, align="R")
            pdf.set_xy(x_cursor + eff_inset, val_top + len(lines) * line_h)
            pdf.cell(eff_w, line_h, "S/", border=0, align="R")
        else:
            # Label column: word-wrap, vertically centred, with indent on first col
            x_off = LABEL_INDENT if i == 0 else 0
            eff = w - x_off
            lines = _wrap_text(pdf, header, eff - 1)
            block_h = len(lines) * line_h
            y_offset = (header_h - block_h) / 2
            for j, ln_text in enumerate(lines):
                pdf.set_xy(x_cursor + x_off, y_start + y_offset + j * line_h)
                pdf.cell(eff, line_h, ln_text, border=0, align="L")
        x_cursor += w

    pdf.set_xy(x_start, y_start + header_h)


def _emit_table_header(pdf, wrap_headers, all_headers, all_widths, n_label_cols, row_h, inset, inner_w,
                       label_aligns=None):
    """Render the table header row (initial page or after a page break)."""
    pdf.set_x(pdf.l_margin + TABLE_INDENT)
    if wrap_headers:
        _render_wrapped_header(pdf, all_headers, all_widths, n_label_cols, row_h, inset, inner_w)
    else:
        _render_table_header(pdf, all_headers, all_widths, n_label_cols, row_h, inset, inner_w,
                             label_aligns=label_aligns)


# ---------------------------------------------------------------------------
# Row renderers
# ---------------------------------------------------------------------------

def _render_data_row(pdf, row, col_widths_mm, val_width_mm,
                     inset, inner_w, row_h, label_aligns):
    """Render a normal or group_header row."""
    row_type = row["row_type"]

    if row_type == "group_header":
        pdf.ln(BLANK_ROW_SPACING)
        pdf.set_x(pdf.l_margin + TABLE_INDENT)
        pdf.set_font("Helvetica", "BI", FONT_SIZE_DATA)
        pdf.set_text_color(*CHARCOAL)
        for i, label in enumerate(row["labels"]):
            pdf.cell(col_widths_mm[i], row_h, str(label) if label else "", border=0)
        pdf.ln()
        pdf.set_text_color(*BLACK)
        return

    # Normal row
    pdf.set_font("Helvetica", "", FONT_SIZE_DATA)
    pdf.set_text_color(*BLACK)

    for i, label in enumerate(row["labels"]):
        text = str(label) if label else ""
        align = label_aligns[i] if label_aligns and i < len(label_aligns) else "L"
        w = col_widths_mm[i]
        if i == 0 and align == "L":
            pdf.cell(LABEL_INDENT, row_h, "", border=0)
            pdf.cell(w - LABEL_INDENT, row_h, text, border=0, align=align)
        else:
            pdf.cell(w, row_h, text, border=0, align=align)

    for num_str in row["nums"]:
        x0 = pdf.get_x()
        pdf.cell(val_width_mm, row_h, "", border=0)
        pdf.set_xy(x0 + inset, pdf.get_y())
        pdf.cell(inner_w, row_h, num_str, border=0, align="R")
        pdf.set_x(x0 + val_width_mm)

    pdf.ln()


def _render_bold_row(pdf, row, col_widths_mm, val_width_mm,
                     inset, inner_w, row_h, val_col_segments, label_aligns):
    """Render a subtotal, total, or final_total row."""
    row_type = row["row_type"]

    # Top border
    pdf.set_font("Helvetica", "B", FONT_SIZE_DATA)
    y_top = pdf.get_y()
    pdf.set_draw_color(*BLACK)
    pdf.set_line_width(BORDER_SUBTOTAL)
    for _x0, _x1 in val_col_segments:
        pdf.line(_x0, y_top, _x1, y_top)

    pdf.set_text_color(*BLACK)

    # Label cells (no indent for bold rows)
    for i, label in enumerate(row["labels"]):
        text = str(label) if label else ""
        align = label_aligns[i] if label_aligns and i < len(label_aligns) else "L"
        pdf.cell(col_widths_mm[i], row_h, text, border=0, align=align)

    # Value cells
    for num_str in row["nums"]:
        x0 = pdf.get_x()
        pdf.cell(val_width_mm, row_h, "", border=0)
        pdf.set_xy(x0 + inset, pdf.get_y())
        pdf.cell(inner_w, row_h, num_str, border=0, align="R")
        pdf.set_x(x0 + val_width_mm)

    pdf.ln()

    # Bottom border for final_total (thicker double-underline style)
    if row_type == "final_total":
        pdf.set_draw_color(*BLACK)
        pdf.set_line_width(BORDER_TOTAL)
        y = pdf.get_y()
        for _x0, _x1 in val_col_segments:
            pdf.line(_x0, y, _x1, y)


# ---------------------------------------------------------------------------
# Main table renderer (thin dispatcher)
# ---------------------------------------------------------------------------

def _render_table(pdf: FinancialPDF, rows, col_headers, value_headers,
                  col_widths_mm, val_width_mm, *, alternating=False,
                  wrap_headers=False, label_aligns=None):
    """Render a data table.

    col_headers  : list of header labels for label columns (e.g. ["CC", "CENTRO DE COSTO"])
    value_headers: list of header labels for value columns (e.g. ["Q1 2025", "Q1 2024", ...])
    col_widths_mm: list of widths in mm for label columns
    val_width_mm : width in mm for each value column
    alternating  : if True, normal rows alternate between white and ZEBRA_GRAY
    wrap_headers : if True, use multi-line wrapping for header text
    label_aligns : list of alignment strings ("L", "C", "R") per label column; defaults to "L"
    """
    all_headers = col_headers + value_headers
    all_widths = col_widths_mm + [val_width_mm] * len(value_headers)
    row_h = ROW_HEIGHT
    inset = val_width_mm * VALUE_INSET_PCT / 100
    n_label_cols = len(col_headers)
    inner_w = val_width_mm - 2 * inset

    _emit_table_header(pdf, wrap_headers, all_headers, all_widths, n_label_cols, row_h, inset, inner_w,
                       label_aligns=label_aligns)

    # Pre-compute fixed line segments per value column
    LINE_MARGIN = 1.5
    value_cols_x = pdf.l_margin + TABLE_INDENT + sum(col_widths_mm)
    n_val_cols = len(value_headers)
    pdf.set_font("Helvetica", "B", FONT_SIZE_DATA)
    global_max_tw = 0.0
    for row in rows:
        if row["row_type"] not in ("subtotal", "total", "final_total"):
            continue
        for num_str in row["nums"]:
            if num_str:
                tw = pdf.get_string_width(num_str)
                if tw > global_max_tw:
                    global_max_tw = tw
    line_w = global_max_tw + LINE_MARGIN
    val_col_segments = []
    for j in range(n_val_cols):
        col_right = value_cols_x + (j + 1) * val_width_mm - inset
        val_col_segments.append((col_right - line_w, col_right))

    # --- Data rows ---
    pdf.set_font("Helvetica", "", FONT_SIZE_DATA)
    data_row_idx = 0

    for row in rows:
        if pdf.get_y() + row_h > pdf.h - PAGE_MARGIN:
            pdf.add_page()
            _emit_table_header(pdf, wrap_headers, all_headers, all_widths, n_label_cols, row_h, inset, inner_w,
                               label_aligns=label_aligns)
            pdf.set_font("Helvetica", "", FONT_SIZE_DATA)

        row_type = row["row_type"]

        if row_type == "blank":
            pdf.ln(BLANK_ROW_SPACING)
            continue

        pdf.set_x(pdf.l_margin + TABLE_INDENT)

        if row_type == "group_header":
            _render_data_row(pdf, row, col_widths_mm, val_width_mm,
                             inset, inner_w, row_h, label_aligns)
            continue

        if row_type in ("subtotal", "total", "final_total"):
            _render_bold_row(pdf, row, col_widths_mm, val_width_mm,
                             inset, inner_w, row_h, val_col_segments, label_aligns)
            data_row_idx = 0
        else:
            _render_data_row(pdf, row, col_widths_mm, val_width_mm,
                             inset, inner_w, row_h, label_aligns)
            data_row_idx += 1


# ---------------------------------------------------------------------------
# Width calculator
# ---------------------------------------------------------------------------

def _compute_widths(pdf: FinancialPDF, n_val_cols, label_pcts):
    """Return (list of label col widths in mm, single val col width in mm)."""
    usable = pdf.w - pdf.l_margin - pdf.r_margin - 2 * TABLE_INDENT
    total_label_pct = sum(label_pcts)
    col_widths = [usable * (p / 100) for p in label_pcts]
    remaining = usable * ((100 - total_label_pct) / 100)
    val_width = remaining / n_val_cols if n_val_cols > 0 else remaining
    return col_widths, val_width
