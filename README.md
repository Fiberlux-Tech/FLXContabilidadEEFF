# FLXContabilidadEEFF - Financial Report Generator

Automated financial report generation system for Peruvian companies. Reads accounting data from a SQL Server database, transforms it according to business rules, and generates **Profit & Loss (P&L)** and **Balance Sheet (BS)** reports in both **Excel** and **PDF** formats, with optional email distribution.

Supports four companies: **FIBERLINE**, **FIBERLUX**, **FIBERTECH**, and **NEXTNET**.

## Project Structure

```
FLXContabilidadEEFF/
├── config/          # Configuration (DB, email, company metadata, calendar, note definitions)
├── core/            # CLI parsing, pipeline orchestration, email sending
├── data/            # Database connectivity (pyodbc), SQL queries, concurrent data fetching
├── export/
│   ├── excel/       # Excel report building, export, and styling (openpyxl)
│   └── pdf/         # PDF report building, export, rendering, and constants (fpdf2)
├── models/          # Dataclasses for report structures (PnLReportData, PdfReportData, etc.)
├── rules/           # Account classification rules and business logic tables
├── transforms/      # Data cleaning, P&L/BS classification, aggregation, statement building
├── tests/           # Test suite (pytest)
├── main.py          # CLI entry point
└── gui.py           # Desktop GUI entry point (Tkinter)
```

## Features

### Report Generation
- **P&L Reports**: Monthly, quarterly, or full-year Profit & Loss statements with 14 classification categories (revenue, cost, expenses, D&A, financial results, etc.)
- **Balance Sheet Reports**: Cumulative BS with ACTIVO/PASIVO/PATRIMONIO sections, dynamic reclassification rules, and imbalance detection
- **PDF Reports**: Multi-page professional PDFs with cover page, 4-column comparative layout (current month, YTD, prior year month, prior year YTD), 15+ numbered detail notes, and company branding
- **Excel Reports**: Multi-sheet workbooks with P&L summary, CECO detail, sales breakdown, BS summary, BS detail notes per partida, NIT top-20 rankings, and a validator sheet

### Data Pipeline
- **Concurrent Data Fetching**: 5 independent SQL queries run in parallel via `ThreadPoolExecutor`
- **Smart Caching**: Previous-year data cached in Parquet format with a 30-day TTL
- **Configurable via Environment Variables**: Database, email, output directory, logging level, and strict mode all controlled through `.env`

### Output & Distribution
- **Dual Email Backends**: Windows-native Outlook COM automation + cross-platform SMTP with TLS
- **Test Email Mode**: `--test-email` flag to verify email configuration before running heavy reports
- **CLI Flags**: `--no-email`, `--excel-only`, `--company`, `--year`, `--month`, `--quarter`

### User Interfaces
- **CLI** (`main.py`): Full-featured command-line interface with interactive prompts
- **GUI** (`gui.py`): Tkinter desktop app with company/period selection, checkboxes for Excel/PDF/email, and threaded non-blocking execution

## Setup

### Requirements

- Python 3.10+
- SQL Server with ODBC driver
- Dependencies listed in `requirements.txt`

```bash
pip install -r requirements.txt
```

### Environment Variables

Create a `.env` file in the project root:

```env
# Database
DB_DRIVER=ODBC Driver 18 for SQL Server
DB_SERVER=your_server
DB_DATABASE=your_database
DB_UID=your_user
DB_PWD=your_password

# Email (optional)
EMAIL_BACKEND=outlook   # or "smtp"
EMAIL_TO=recipient@example.com

# Application
OUTPUT_DIR=.
LOG_LEVEL=INFO
```

## Usage

### CLI

```bash
# Interactive mode
python main.py

# Specify all parameters
python main.py --company FIBERLUX --year 2025 --month 6

# Quarterly report, no email
python main.py --company FIBERLINE --year 2025 --quarter 2 --no-email

# Excel only (skip PDF)
python main.py --company FIBERTECH --year 2025 --month 12 --excel-only

# Test email configuration
python main.py --test-email
```

### GUI

```bash
python gui.py
```

### Tests

```bash
pytest
```

## TO-DO

1. **Break the code into a more modular codebase.** Excel export should be independent of PDF export and viceversa, so each can run without depending on the other.
2. **Finish the financial statements.** We need feedback from accounting to continue; currently blocked waiting on their response.
