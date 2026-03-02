# Export Layer — Excel & PDF Generation

> Detailed reference for how Excel workbooks and PDF reports are built and styled.

## Excel Export (excel_export.py + excel_styles.py)

### Entry Point

```python
export_to_excel(output_path: str, year: int, data: PnLReportData) -> None
```

Single function orchestrates entire workbook generation.

### Sheet Generation Order

```
1. PL                     — P&L summary statement
2. BS                     — Balance Sheet summary
3. Nota 01 ... Nota NN    — Config-driven nota sheets (from nota_config.NOTA_GROUPS)
4. DETALLE_CC_x_CC        — Five-section expanded detail (COSTO, GASTO VENTA, GASTO ADMIN, D&A-COSTO, D&A-GASTO)
5. VALIDADOR1             — Summary by CUENTA
6. VALIDADOR2             — Summary by CECO
7. VALIDADOR3             — Summary by CECO x CUENTA
8. VALIDADOR_BS           — BS validation (if BS data present)
```

### Layout Constants

| Constant | Value | Meaning |
|----------|-------|---------|
| `TITLE_ROW` | 2 | Sheet title cell (1-indexed Excel row) |
| `DATA_START_ROW` | 3 | Pandas `startrow` (0-indexed, = Excel row 4) |
| `HEADER_ROW` | 4 | Column headers (1-indexed) |
| `EXCEL_DATA_ROW` | 5 | First data row (1-indexed) |
| `COL_B_WIDTH_PL` | 40mm | P&L statement label width |
| `COL_B_WIDTH_BS` | 55mm | Balance sheet label width |
| `COL_B_WIDTH_DEFAULT` | 40mm | Standard label width |
| `VAL_COL_WIDTH` | 11mm | Standard value column width |
| `BS_VAL_COL_WIDTH` | 14mm | BS value column width |
| `COL_A_WIDTH` | 5mm | Row number / spacing column |

### Column Positions

| Constant | Column | Value |
|----------|--------|-------|
| `PL_TOTAL_COL` | O (15) | P&L TOTAL column position |
| `STANDARD_TOTAL_COL` | P (16) | Detail sheet TOTAL |
| `WIDE_TOTAL_COL` | R (18) | CC x CC detail TOTAL |
| `STANDARD_FIRST_VAL_COL` | D (4) | First value column (standard layout) |
| `WIDE_FIRST_VAL_COL` | F (6) | First value column (wide layout) |

### Sheet Layout Patterns

**Standard Layout (detail sheets):**
```
     A    B (40mm)         C        D-O (11mm each)    P (11mm)
  1  [empty]
  2       TITLE
  3  [header row]
  4       LABEL_COL   DESC_COL   JAN  FEB  ... DEC    TOTAL
  5       data...
```

**Wide Layout (CC x CC):**
```
     A   B    C      D    E (40mm)    F-Q (11mm each)   R
  1  [empty]
  2      TITLE
  3  [header row]
  4      CECO DESC   CUENTA DESC     JAN  FEB  ... DEC  TOTAL
  5      data...
```

### Styling Pipeline (Applied After All Data Written)

```
1. style_init(ws, col_b_width)
   └── Set column A/B widths + style title cell

2. apply_number_format(ws)
   └── Global: '#,##0;(#,##0);-' on all numeric cells

3. Sheet-specific styling:
   ├── style_pl_sheet(ws)        — Adjust widths, clear PARTIDA_PL header
   ├── style_bs_sheet(ws)        — Wider value columns (14mm)
   ├── style_two_table_sheet(ws) — Multi-table nota sheets
   ├── style_detalle_cc_x_cc(ws) — 5-section layout detection
   ├── style_sales_details(ws)   — Dual-section (ingresos + proyectos)
   └── style_validator_sheets()  — Standard layout

4. Targeted passes:
   ├── highlight_excluded_rows(ws, excluded_cuentas) — Orange fill
   ├── format_subtotal_rows(ws, labels)              — Purple fill
   └── bold_total_rows(ws)                           — Bold TOTAL rows
```

### Number Format

```
Excel: '#,##0;(#,##0);-'
  Positive:  1,234,567
  Negative: (1,234,567)
  Zero:     -
```

### Color Palette (Excel)

| Name | Hex | Usage |
|------|-----|-------|
| Header fill | `#D9D9D9` | Gray background for column headers |
| Highlight fill | `#FCE4D6` | Light orange for excluded account rows |
| Subtotal fill | `#E4DFEC` | Light purple for P&L subtotal rows |
| Validator tab | `#8B0000` | Dark red tab color for validator sheets |

### Typography (Excel)

| Style | Font | Size | Weight |
|-------|------|------|--------|
| Default | Calibri | 11pt | Normal |
| Title | Calibri | 12pt | Bold |
| Header | Calibri | 11pt | Bold |
| Total rows | Calibri | 11pt | Bold |

### Nota Sheet Routing

The nota sheets are rendered based on `RenderPattern` from `nota_config.py`:

```python
match entry.pattern:
    case RenderPattern.BS_DETAIL:
        _write_single_bs_sheet(...)           # Single BS detail table
    case RenderPattern.BS_DETAIL_WITH_NIT:
        _write_relacionadas_sheet(...)        # BS detail + NIT pivot
    case RenderPattern.PL_DETAIL_CECO:
        _write_single_nota(..., by_ceco)      # P&L by cost center
    case RenderPattern.PL_DETAIL_CUENTA:
        _write_single_nota(..., by_cuenta)    # P&L by account
    case RenderPattern.SALES_INGRESOS:
        _write_sales_details(...)             # Revenue detail
    case RenderPattern.SALES_PROYECTOS:
        _write_sales_details(...)             # Projects detail
```

### Multi-Table Stacking

When a `NotaGroup` has multiple entries, tables are stacked vertically with gaps:

```
Row N:     Table 1 Title
Row N+1:   Table 1 Headers
Row N+2:   Table 1 Data...
           ...
Row M:     [EXPANDED_GAP_ROWS = 5 blank rows]
Row M+5:   Table 2 Title
Row M+6:   Table 2 Headers
           ...
```

## PDF Export (pdf_export.py + pdf_reports.py)

### Entry Point

```python
export_to_pdf(output_path: str, data: PdfReportData) -> None
```

### PDF Library

Uses **fpdf2** (`from fpdf import FPDF`) with custom subclass:

```python
class FinancialPDF(FPDF):
    is_cover: bool              # Suppress header/footer on cover
    show_company_in_header: bool # Company name in page header
    _title: str                  # Report title
    _subtitle: str               # Period subtitle

    def header(self): ...        # Dynamic page header
    def footer(self): ...        # "Confidencial" + page number
    def _set_navy_bold(): ...    # Navy color helper
    def _set_charcoal(): ...     # Charcoal color helper
```

### Page Structure

```
┌─────────────────────────────────────────────────┐
│  PAGE HEADER (15mm margins)                     │
│  Company Name (9pt) ─────── Report Title (11pt) │
│  ──────────────────── Subtitle (7pt)            │
│                                                 │
│  CONTENT AREA                                   │
│  Tables, subheaders, notes...                   │
│                                                 │
│                                                 │
│  PAGE FOOTER                                    │
│  Confidencial ──────────────── Página N de M    │
└─────────────────────────────────────────────────┘
```

### Document Sections

```
1. COVER PAGE
   - Company logo (from logos/ directory)
   - Company name (26pt)
   - Legal name and RUC
   - Report type ("Estado de Resultados" / "Estado de Situación Financiera")
   - Period date ("AL 28 DE FEBRERO DE 2026")
   - Currency note ("Expresado en Soles")

2. P&L SUMMARY
   - Full P&L statement table

3. BS SUMMARY
   - Full Balance Sheet table

4. NOTA PAGES (config-driven, same NOTA_GROUPS as Excel)
   - Each nota gets a subheader ("Nota 01. Efectivo y Equivalentes...")
   - Tables with appropriate layout per RenderPattern

5. NIT PIVOT PAGES (if related-party data exists)
   - Cross-tabulation of NIT × Account for related-party analysis
```

### Color Palette (PDF — RGB Tuples)

| Name | RGB | Hex | Usage |
|------|-----|-----|-------|
| Navy | (0, 35, 102) | `#002366` | Titles, headers, subheaders |
| Charcoal | (51, 51, 51) | `#333333` | Body text |
| White | (255, 255, 255) | `#FFFFFF` | Background |
| Light Gray | (242, 242, 242) | `#F2F2F2` | Total rows |
| Muted Blue | (230, 234, 242) | `#E6EAF2` | Subtotal rows |
| Zebra Gray | (240, 243, 248) | `#F0F3F8` | Alternating row fill |
| Line Gray | (208, 208, 208) | `#D0D0D0` | Table borders |
| Footer Gray | (136, 136, 136) | `#888888` | Footer text |
| Black | (0, 0, 0) | `#000000` | Standard text |

### Font Sizes (PDF — Points)

| Context | Size | Style |
|---------|------|-------|
| Cover company name | 26pt | Bold |
| Cover info | 10pt | Normal |
| Cover currency note | 9pt | Italic |
| Page header (company) | 9pt | Bold |
| Page header (title) | 11pt | Bold |
| Subtitle | 7pt | Normal |
| Table header | 6pt | Bold |
| Subheader (nota titles) | 8pt | Bold |
| Data rows | 6.5pt | Normal |
| Footer | 6pt | Normal |

### Layout Constants (mm)

| Constant | Value | Purpose |
|----------|-------|---------|
| `PAGE_MARGIN` | 15 | Left/right margin |
| `PAGE_TOP_MARGIN` | 20 | Top margin |
| `ROW_HEIGHT` | 4.5 | Data row height |
| `HEADER_ROW_EXTRA` | 1 | Extra height for header rows |
| `BLANK_ROW_SPACING` | 2 | Between sections |
| `SECTION_SPACING` | 10 | Between notes |
| `BORDER_TOTAL` | 0.4mm | Total row border width |
| `BORDER_SUBTOTAL` | 0.2mm | Subtotal border width |
| `BORDER_NORMAL` | 0.1mm | Normal border width |
| `BORDER_COVER` | 0.8mm | Cover page border |

### Column Width Computation

Percentage-based allocation of available page width:

| Layout | Label Column % | Condition |
|--------|---------------|-----------|
| P&L (narrow, ≤2 value cols) | [40%] | Single label column |
| P&L (wide, >2 value cols) | [32%] | Single label column |
| Detail (narrow) | [8%, 32%] | Two label columns |
| Detail (wide) | [7%, 23%] | Two label columns |
| NIT pivot | [8%, 30%] | NIT + RAZON_SOCIAL |

Remaining width is divided equally among value columns.

### DataFrame → PDF Rendering Pipeline

```
pd.DataFrame
    │
    ▼
_df_to_rows(df, label_cols, value_cols)
    │  → list[dict] with {"labels", "nums", "row_type"}
    ▼
_drop_zero_rows(rows)
    │  → Removes all-zero normal rows
    │  → Removes orphaned group headers
    ▼
_render_table(pdf, rows, col_headers, value_headers, ...)
    │  → Writes cells to PDF page
    │  → Auto page-break with header re-emission
    ▼
PDF output
```

### Row Type Classification

| row_type | Condition | Styling |
|----------|-----------|---------|
| `blank` | All labels/values empty | Spacing only, no output |
| `group_header` | CUENTA_CONTABLE == `"__GROUP__"` | Bold italic, light indent |
| `normal` | Regular data | Alternating zebra fill |
| `subtotal` | Label in PL_SUBTOTAL_LABELS or BS_SUBTOTAL_LABELS | Bold, muted blue fill, top border |
| `total` | Label contains "TOTAL" | Bold, light gray fill, top+bottom borders |
| `final_total` | "UTILIDAD NETA", "TOTAL ACTIVO", etc. | Bold, gray fill, **double bottom border** |

### Number Formatting (PDF)

```python
_fmt_number(value):
    Zero/None/NaN:  "—" (em dash)
    Positive:       "1,234,567"
    Negative:       "(1,234,567)"
```

### Efectivo (Cash) Grouping Pattern

For the "Efectivo y Equivalentes" note, accounts are grouped into categories:

```
_EFECTIVO_GROUPS = {
    "10.1":  "Caja",
    "10.4":  "Cuentas corrientes",
    "10.6":  "Depositos a plazo",
    ...
}
```

Two rendering modes:
1. **`_inject_efectivo_groups(df)`** — Insert sentinel rows as group headers (detailed view)
2. **`_aggregate_efectivo_by_group(df)`** — Sum accounts per group (summary view)

Sentinel rows use `CUENTA_CONTABLE = "__GROUP__"` and are detected by `_df_to_rows()`.

### Page Break Handling

In `_render_table()`:
```python
if pdf.get_y() + row_height > pdf.h - PAGE_MARGIN:
    pdf.add_page()
    _emit_table_header(...)  # Re-emit column headers on new page
```

### Cover Page Rendering

`_render_cover(pdf, data)`:
- Logo image from `logos/{company_code}.png`
- Company legal name and RUC from `company_config.COMPANY_META`
- Period label built from `period_type` and `period_num`
- Date format: "AL {day} DE {MONTH_ES} DE {year}" (Spanish)

## Shared Patterns Between Excel and PDF

### Configuration-Driven Notes

Both exports iterate `nota_config.numbered_groups(has_data_fn)`:

```python
for group, numbered_entries in numbered_groups(has_data_fn):
    for nota_num, entry in numbered_entries:
        title = nota_title(nota_num, entry.label)
        # ... render according to entry.pattern
```

This ensures identical note numbering and ordering in both outputs.

### Subtotal and Total Detection

Both exports use the same label sets from `account_rules.py`:
- `PL_SUBTOTAL_LABELS` — 5 P&L subtotal rows
- `BS_SUBTOTAL_LABELS` — 4 BS subtotal/total rows
- `BS_PARTIDA_LABELS` — 28 BS partida labels (for section headers)

### Number Conventions

Both outputs use the same accounting number format:
- Positive: displayed as-is with thousands separator
- Negative: wrapped in parentheses `(value)`
- Zero: dash or em-dash

### Data Source: Same PnLReportData

Excel and PDF share the same `PnLReportData` container. PDF uses a subset (`PdfReportData`) with period-aware column names added.
