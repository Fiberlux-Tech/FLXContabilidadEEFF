"""PDF layout constants — colors, dimensions, fonts, borders, sentinels."""

from pathlib import Path


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

LOGOS_DIR = Path(__file__).parent / "logos"

# ---------------------------------------------------------------------------
# Color palette
# ---------------------------------------------------------------------------

NAVY = (0, 35, 102)        # #002366
CHARCOAL = (51, 51, 51)    # #333333
WHITE = (255, 255, 255)
LIGHT_GRAY = (242, 242, 242)   # #F2F2F2  — total rows
MUTED_BLUE = (230, 234, 242)   # #e6eaf2  — subtotal rows
ZEBRA_GRAY = (240, 243, 248)   # #F0F3F8  — alternating row fill
LINE_GRAY = (208, 208, 208)    # #D0D0D0  — cell borders
BLACK = (0, 0, 0)
FOOTER_GRAY = (136, 136, 136)

# ---------------------------------------------------------------------------
# Layout constants (mm)
# ---------------------------------------------------------------------------

PAGE_MARGIN = 20               # left / right / auto-break bottom margin
NOTA_DESC_INDENT = 5           # mm indent for the "El rubro está constituido..." line
TABLE_INDENT = 10              # extra mm the table is inset from the page margin on both sides
ROW_HEIGHT = 4.5               # mm per data row
VALUE_INSET_PCT = 15           # % inset on each side of value columns
HEADER_ROW_EXTRA = 1           # extra mm added to row height in header row
BLANK_ROW_SPACING = 2          # mm for blank separator rows
SECTION_SPACING = 10           # mm between note sections on same page

PAGE_TOP_MARGIN = 20           # mm from top of page to start of header

HEADER_CELL_HEIGHT = 4         # company / title lines in page header
SUBTITLE_CELL_HEIGHT = 3.5     # subtitle line in page header
HEADER_BOTTOM_MARGIN = 12      # ln() after header block

FOOTER_Y_OFFSET = -12          # set_y offset for footer
FOOTER_CELL_HEIGHT = 5         # cell height for footer text

COVER_LOGO_Y = 25              # mm from top for logo
COVER_LOGO_WIDTH = 25          # mm logo width
COVER_LOGO_BOTTOM_GAP = 30     # mm added to y after logo
COVER_COMPANY_CELL_H = 14     # cell height for cover company name
COVER_BLOCK_Y = 120            # mm from top for info block
COVER_BLOCK_X = 25             # mm left offset for info block
COVER_LINE_HEIGHT = 5.5        # mm per line in cover info block
COVER_BORDER_PADDING = 12     # breathing room on the right of border
COVER_CONTENT_TOP_PAD = 7     # padding below top border before content
COVER_SPACER_HEIGHT = 4        # spacer cell height inside cover block
COVER_CURRENCY_GAP = 3         # ln() before currency note
COVER_BOTTOM_BORDER_GAP = 5   # padding below last line to bottom border

SUBHEADER_CELL_HEIGHT = 5      # cell height for note subheader
SUBHEADER_BOTTOM_GAP = 1       # ln() after subheader

PL_TOP_GAP = 3                 # ln() before PL/BS table
NOTA_COL_WIDTH = 10            # mm for the "Nota" column in PL/BS summary tables

LABEL_INDENT = 2               # mm left-indent applied to normal (non-total/subtotal) label cells

# ---------------------------------------------------------------------------
# Row type sentinels
# ---------------------------------------------------------------------------

_TOTAL_LABEL = "TOTAL"
_GROUP_SENTINEL = "__GROUP__"
_FINAL_TOTAL_LABEL = "UTILIDAD NETA"
_BS_FINAL_TOTAL_LABELS = {"TOTAL ACTIVO", "TOTAL PASIVO Y PATRIMONIO"}

# ---------------------------------------------------------------------------
# Column width proportions (percentage of usable width)
# ---------------------------------------------------------------------------

PL_LABEL_PCT_NARROW = [40]
PL_LABEL_PCT_WIDE = [32]
DETAIL_LABEL_PCT_NARROW = [40]
DETAIL_LABEL_PCT_WIDE = [30]
DETAIL_2COL_LABEL_PCT_NARROW = [13, 32]
DETAIL_2COL_LABEL_PCT_WIDE = [11, 23]
MAX_NARROW_VALUE_COLS = 2
NIT_LABEL_PCTS = [13, 30]

# ---------------------------------------------------------------------------
# Font sizes (pt)
# ---------------------------------------------------------------------------

FONT_SIZE_DATA = 6.5
FONT_SIZE_HEADER = 6
FONT_SIZE_SUBHEADER = 8
FONT_SIZE_PAGE_HEADER_COMPANY = 9
FONT_SIZE_PAGE_HEADER_TITLE = 11
FONT_SIZE_SUBTITLE = 7
FONT_SIZE_FOOTER = 6
FONT_SIZE_COVER_COMPANY = 26
FONT_SIZE_COVER_INFO = 10
FONT_SIZE_COVER_CURRENCY = 9

# ---------------------------------------------------------------------------
# Border widths (mm)
# ---------------------------------------------------------------------------

BORDER_TOTAL = 0.4
BORDER_SUBTOTAL = 0.2
BORDER_NORMAL = 0.1
BORDER_COVER = 0.8

# ---------------------------------------------------------------------------
# Zero-row filtering
# ---------------------------------------------------------------------------

_ZERO_STRINGS = {"", "-", "0", "(0)"}

# ---------------------------------------------------------------------------
# Legal suffix abbreviations
# ---------------------------------------------------------------------------

_LEGAL_SUFFIX_REPLACEMENTS = [
    ("SOCIEDAD ANONIMA CERRADA", "S.A.C."),
    ("SOCIEDAD COMERCIAL DE RESPONSABILIDAD LIMITADA", "S.R.L."),
    ("EMPRESA INDIVIDUAL DE RESPONSABILIDAD LIMITADA", "E.I.R.L."),
    ("SOCIEDAD ANONIMA ABIERTA", "S.A.A."),
    ("SOCIEDAD ANONIMA", "S.A."),
]
