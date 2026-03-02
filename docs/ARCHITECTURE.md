# FLXContabilidadEEFF - Architecture Guide

> AI-readable architecture documentation for the FLXContabilidadEEFF financial reporting system.

## Project Purpose

FLXContabilidadEEFF generates P&L (Profit & Loss) and Balance Sheet financial reports in Excel (.xlsx) and PDF formats from SQL Server accounting data. It targets Peruvian accounting standards and supports four companies within the FiberLux group.

## Technology Stack

| Component | Technology | Version |
|-----------|-----------|---------|
| Language | Python | >= 3.10 (uses `int \| None` union syntax) |
| Database | SQL Server via pyodbc | 5.2.x |
| Excel | openpyxl | 3.1.x |
| PDF | fpdf2 | 2.8.x |
| Data | pandas + numpy | 2.2.x / 2.2.x |
| Config | python-dotenv | 1.2.x |
| Email (Windows) | pywin32 (Outlook COM) | 310 |
| Testing | pytest | 9.0.x |

## Module Map

```
FLXContabilidadEEFF/
│
├── ENTRY POINTS
│   ├── main.py              # Application entry point, orchestrates workflow
│   └── cli.py               # CLI argument parsing, interactive prompts
│
├── CONFIGURATION (no inter-dependencies, pure data)
│   ├── config.py            # Environment-based config (frozen dataclasses, LRU cached)
│   ├── company_config.py    # Company metadata (legal names, RUC numbers)
│   ├── account_rules.py     # Chart of accounts classification rules (34 exports)
│   ├── calendar_config.py   # Month/quarter/year period helpers
│   ├── nota_config.py       # Financial statement notes structure (drives Excel+PDF)
│   └── exceptions.py        # Custom exception hierarchy
│
├── DATA LAYER
│   ├── db.py                # Thread-safe connection pool (queue-based, max 5)
│   ├── queries.py           # SQL queries against REPORTES.VISTA_ANALISIS_CECOS
│   └── models.py            # Dataclasses: PeriodContext, PnLReportData, PdfReportData
│
├── TRANSFORM LAYER
│   ├── transforms.py        # Data cleaning, SALDO computation, account classification
│   ├── aggregation.py       # Pivot tables, groupby, month-based summaries
│   └── statement_builder.py # P&L and BS row structure, formulas, reclassification
│
├── EXPORT LAYER
│   ├── pipeline.py          # Orchestrates data fetch → transform → export
│   ├── excel_export.py      # Multi-sheet Excel workbook generation
│   ├── excel_styles.py      # openpyxl styling constants and helpers
│   ├── pdf_export.py        # PDF rendering with fpdf2 (FinancialPDF class)
│   └── pdf_reports.py       # Period-aware aggregation for PDF columns
│
├── COMMUNICATION
│   └── email_sender.py      # Outlook/SMTP email with Strategy pattern
│
├── ASSETS
│   └── logos/               # Company logos for PDF cover pages
│
└── TESTS
    └── tests/               # 113 pytest tests across 7 modules
```

## Dependency Graph

```
main.py
  ├── cli.py ──→ company_config, calendar_config
  ├── config.py (singleton via LRU cache)
  ├── email_sender.py ──→ config, exceptions
  └── pipeline.py
        ├── db.py ──→ config, exceptions
        ├── queries.py ──→ account_rules, exceptions
        ├── transforms.py ──→ account_rules, exceptions
        ├── aggregation.py ──→ calendar_config, account_rules
        ├── statement_builder.py ──→ calendar_config, account_rules, aggregation, exceptions
        ├── models.py (pure types, no deps)
        ├── excel_export.py ──→ excel_styles, nota_config, models, aggregation
        ├── pdf_export.py ──→ models, account_rules, calendar_config, company_config, nota_config
        ├── pdf_reports.py ──→ calendar_config, models, aggregation, statement_builder
        └── email_sender.py ──→ config, exceptions
```

Key rule: **Configuration modules have zero project dependencies**. Data flows unidirectionally from config → data → transform → export.

## Application Lifecycle

```
1. STARTUP
   main.py → dotenv.load_dotenv() → config.get_config() [cached singleton]

2. CLI RESOLUTION
   cli.parse_args() → cli.resolve_period()
   Returns: (company, year, month, quarter, period_type, period_num)

3. EMAIL VALIDATION (before expensive computation)
   email_sender.get_email_sender().validate_config()

4. PIPELINE EXECUTION (pipeline.run_report)
   a. CONCURRENT DATA FETCH (ThreadPoolExecutor, 5 workers)
      - Each thread gets own pyodbc connection from pool
      - queries.fetch_pnl_data() → P&L accounts (6, 7, 8 prefixes)
      - queries.fetch_bs_data()  → BS accounts (1-5 prefixes), cumulative
      - Previous year data fetched in parallel (with 30-day pickle cache)

   b. EXCEL DATA BUILD
      transforms.prepare_pnl() → filter_for_statements() → assign_partida_pl()
      aggregation.preaggregate() → detail_* functions → pivot_by_month()
      statement_builder.pl_summary() / bs_summary()
      → PnLReportData (19 DataFrame fields)

   c. EXCEL EXPORT
      excel_export.export_to_excel() → openpyxl ExcelWriter
      excel_styles.style_*() → batch styling pass

   d. PDF DATA BUILD (if not --excel-only)
      pdf_reports.*_pdf() → period-aware columns
      → PdfReportData (subset + metadata)

   e. PDF EXPORT
      pdf_export.export_to_pdf() → FinancialPDF → file

   f. MEMORY CLEANUP
      Explicit `del` of large DataFrames between phases

5. EMAIL (optional, interactive confirmation)
   email_sender.send() → attach files → send via Outlook/SMTP
```

## Key Architectural Decisions

### 1. Configuration as Frozen Dataclasses
All config is immutable (`frozen=True` dataclasses) cached with `@lru_cache(maxsize=1)`. Prevents accidental mutation at runtime.

### 2. Thread-Safe Connection Pool
Custom `_ConnectionPool` using `queue.Queue` with connection validation (`SELECT 1`) before reuse. Each thread in the `ThreadPoolExecutor` gets its own connection since pyodbc is not thread-safe.

### 3. Declarative Business Rules
Account classification rules live in `account_rules.py` as pure data (dicts, tuples, sets). No functions — transforms.py reads these constants and applies them via `np.select()` vectorized operations.

### 4. Configuration-Driven Report Notes
`nota_config.py` defines `NOTA_GROUPS` as a tuple of `NotaGroup` objects. Both Excel and PDF rendering iterate this same structure via `numbered_groups()`. Adding/reordering notes requires only modifying `NOTA_GROUPS`.

### 5. Deferred Styling (Excel)
Data is written to all sheets first (unstyled), then styling is applied in a batch pass at the end. This decouples data logic from presentation and enables flexible composition.

### 6. Row Dictionary Abstraction (PDF)
DataFrames are converted to intermediate `{"labels": [...], "nums": [...], "row_type": "..."}` dicts before PDF rendering. This allows filtering (zero rows), classification (subtotal/total), and consistent rendering regardless of DataFrame shape.

### 7. Previous-Year Caching
Immutable historical data is cached as pickle files with 30-day TTL. Reduces database load for repeated report generation within the same period.

### 8. Non-Fatal Email
Email failures are logged as warnings but do not fail the pipeline. Report files are always generated first.

## Error Handling Strategy

```
PlantillasError (base)
├── ConfigurationError    → Missing env vars, invalid .env
├── DatabaseError         → Connection/driver issues
│   └── QueryError        → SQL execution failures
├── ExportError           → File I/O, locked files, data validation
├── EmailError            → SMTP/Outlook failures
├── PipelineError         → Orchestration issues
└── DataValidationError   → Missing DataFrame columns
```

**Handling tiers in main.py:**
- `ConfigurationError` → log + `sys.exit(1)` (early, before computation)
- `PlantillasError` → log with type + `sys.exit(1)`
- `Exception` → log full traceback + `sys.exit(1)`
- `EmailError` → log warning (non-fatal)

## File Naming Conventions

| Type | Pattern | Example |
|------|---------|---------|
| Modules | lowercase_snake_case.py | `excel_export.py` |
| Classes | PascalCase | `PnLReportData`, `FinancialPDF` |
| Constants | SCREAMING_SNAKE_CASE | `TOTAL_COL`, `BS_ACCOUNT_PREFIXES` |
| Private functions | _prefixed | `_fetch_data()`, `_detail_pivot()` |
| DataFrame columns | UPPERCASE_SPANISH | `CUENTA_CONTABLE`, `CENTRO_COSTO` |
| Logger names | "plantillas.module" | `logging.getLogger("plantillas.pipeline")` |

## Related Documentation

- [DATA_FLOW.md](DATA_FLOW.md) — Data pipeline, transformations, column conventions
- [CODING_CONVENTIONS.md](CODING_CONVENTIONS.md) — Patterns, typing, imports
- [CONFIGURATION.md](CONFIGURATION.md) — Environment variables, business rules
- [EXPORT_LAYER.md](EXPORT_LAYER.md) — Excel and PDF generation details
- [TESTING.md](TESTING.md) — Test patterns and coverage
- [GROUPING_PATTERN.md](GROUPING_PATTERN.md) — PDF grouping implementation guide
