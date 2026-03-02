# Testing Guide

> Test structure, patterns, fixtures, and coverage for PlantillasFLX.

## Quick Start

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific module
pytest tests/test_transforms.py

# Run specific test class
pytest tests/test_pdf_export_units.py::TestFilterZeroRows
```

## Test Framework

- **Framework:** pytest 9.0.2
- **No additional plugins** (no pytest-cov, pytest-mock, etc.)
- **Dev dependencies:** Only `pytest` in `requirements-dev.txt`

## Test Organization

```
tests/
├── conftest.py                  # Shared fixtures (autouse config clear, raw_pnl_df)
├── test_db.py                   # Database config (3 tests)
├── test_email_sender.py         # Email backends (12 tests)
├── test_exports.py              # Integration: Excel/PDF export (12 tests)
├── test_pdf_export_units.py     # PDF helper units (60 tests)
├── test_queries.py              # Query constants (4 tests)
├── test_reports.py              # Aggregation functions (17 tests)
└── test_transforms.py           # Data pipeline (13 tests)

Total: 113 tests, ~1,029 lines of test code
```

## Fixtures (conftest.py)

### _clear_config_cache (autouse)

```python
@pytest.fixture(autouse=True)
def _clear_config_cache():
    """Clears get_config() LRU cache before each test."""
    get_config.cache_clear()
```

Ensures environment variable changes take effect between tests. Runs automatically for every test.

### raw_pnl_df

Minimal DataFrame mimicking `fetch_pnl_data()` output. Contains 12 rows covering all major P&L account categories:

| Row | CUENTA_CONTABLE | CENTRO_COSTO | Category |
|-----|----------------|--------------|----------|
| 1 | 70.1.1.1.01 | 100 | INGRESOS ORDINARIOS |
| 2 | 75.9.9.1.01 | 100 | INGRESOS PROYECTOS |
| 3 | 62.1.1.1.01 | 100 (prefix "1") | COSTO |
| 4 | 63.1.1.1.01 | 200 (prefix "2") | GASTO VENTA |
| 5 | 63.2.1.1.01 | 300 (prefix "3") | GASTO ADMIN |
| 6 | 68.1.1.1.01 | 600 (prefix "6") | D&A - COSTO |
| 7 | 68.2.1.1.01 | 300 | D&A - GASTO |
| 8 | 67.1.1.1.01 | 700 (prefix "7") | RESULTADO FINANCIERO |
| 9 | 77.1.1.1.01 | 700 | RESULTADO FINANCIERO (ingresos) |
| 10 | 89.1.1.1.01 | 100 | IMPUESTO A LA RENTA |
| 11 | 60.1.1.1.01 | 100 | Excluded (filtered out) |
| 12 | 79.1.1.1.01 | 100 | Excluded (EXCLUDED_CUENTA) |

### Derived Fixtures (in test modules)

| Fixture | Source | Used By |
|---------|--------|---------|
| `classified_df` | `prepare_stmt(raw_pnl_df)` | test_exports, test_reports |
| `excel_report_data` | `build_excel_data(raw_pnl_df)` | test_exports |
| `pdf_report_data` | `build_pdf_data(...)` | test_exports |

## Test Modules Detail

### test_db.py (3 tests)

Tests database connection string builder (`_build_conn_str`):
- Validates correct ODBC connection string format
- Tests TLS/encryption parameters
- Tests trust certificate settings

**Not tested:** Connection pooling, actual connections, query execution.

### test_email_sender.py (12 tests)

```
TestGetEmailSender (6 tests)
├── Platform auto-detection (Windows → Outlook, Linux → SMTP)
├── EMAIL_BACKEND override ("outlook", "smtp")
├── Invalid backend rejection
└── Protocol compliance (isinstance checks)

TestValidateConfig (6 tests)
├── SMTP: requires EMAIL_TO, SMTP_HOST, SMTP_PORT, EMAIL_FROM
├── Outlook: requires EMAIL_TO only
└── Missing config raises ConfigurationError
```

**Pattern:** Uses `monkeypatch.setenv()` and `monkeypatch.setattr(sys, "platform", ...)` for environment and platform mocking.

### test_exports.py (12 tests)

Integration tests that run the full pipeline:

```
TestBuildExcelData (5 tests)
├── PnLReportData is populated correctly
├── PL summary has expected row count
├── Sales details present
├── Excluded cuentas tracked
└── Resultado financiero split correctly

TestBuildPdfData (3 tests)
├── PdfReportData populated
├── Column names correct for full-year
└── BS details populated

TestExportFiles (4 tests)
├── Excel file created and PL sheet exists
├── PDF file created with multiple pages
├── Excel file has data in PL sheet
└── PDF file is non-empty
```

**Pattern:** Uses `tmp_path` fixture for temporary file output. Tests file creation and basic content validation.

### test_pdf_export_units.py (60 tests)

Largest test module. Tests low-level PDF helper functions:

```
TestFilterZeroRows (7 tests)
├── Keeps non-zero rows, removes all-zero rows
├── Preserves blank/total/subtotal/group_header rows
├── Handles mixed zero strings ("", "-", "0", "(0)")
└── Handles empty input

TestRemoveOrphanedGroupHeaders (5 tests)
├── Removes group headers followed by blank/another header
├── Keeps headers with normal rows after them
└── End-of-list headers removed

TestDropZeroRows (3 tests)
├── Combined filter + orphan removal
└── End-to-end zero filtering

TestPlRowType (12 tests)
├── Blank detection (all empty values)
├── Total row detection ("TOTAL" label)
├── Final total ("UTILIDAD NETA")
├── Subtotal labels (PL_SUBTOTAL_LABELS)
└── Normal rows (default)

TestBsRowType (10 tests)
├── Blank detection
├── Final totals ("TOTAL ACTIVO", "TOTAL PASIVO Y PATRIMONIO")
├── Section totals ("TOTAL PASIVO")
└── Normal rows

TestDfToRows (8 tests)
├── Correct label/num extraction
├── Number formatting (positive, negative, zero)
├── Group sentinel detection ("__GROUP__")
├── Numeric column name handling
└── None/NaN value handling

TestInjectEfectivoGroups (8 tests)
├── Group header insertion at correct positions
├── Ordering within groups
├── Accounts without group assignment
└── Empty DataFrame handling

TestEfectivoGroupLookup (5 tests)
├── Prefix matching for all EFECTIVO groups
├── Unknown prefix returns None
└── Edge cases (short codes, exact matches)

TestFmtNumber (2 tests)
├── Positive/negative/zero formatting
└── None/NaN handling
```

### test_queries.py (4 tests)

```
TestQueryConstants (2 tests)
├── BS_ACCOUNT_PREFIXES contains "1"-"5"
└── PL account prefixes are "6", "7", "8"

TestFetchDelegation (2 tests)
├── fetch_pnl_data calls _fetch_data with correct prefixes
└── fetch_bs_data calls _fetch_data with cumulative=True
```

**Pattern:** Uses source inspection (`inspect.getsource()`) to verify delegation patterns without executing actual queries.

### test_reports.py (17 tests)

```
TestSummarize (6 tests)
├── summarize_by_cuenta produces correct columns (months + TOTAL)
├── summarize_by_ceco produces correct columns
├── Month column names are from MONTH_NAMES
├── TOTAL column present
└── Data values are correct sums

TestPlSummary (5 tests)
├── PL summary has correct row structure
├── INGRESOS TOTALES calculated correctly
├── UTILIDAD BRUTA formula verified
├── UTILIDAD NETA formula verified
└── All subtotal labels present

TestAppendTotalRow (3 tests)
├── Appends row with "TOTAL" label
├── Sums numeric columns correctly
└── Preserves non-numeric columns

TestResultadoFinanciero (3 tests)
├── Splits into ingresos (77.x) and gastos
├── Both have TOTAL rows
└── Correct DataFrame shapes
```

### test_transforms.py (13 tests)

```
TestPreparePnl (3 tests)
├── Adds SALDO column (CREDITO - DEBITO)
├── Adds MES column from FECHA
└── CENTRO_COSTO is categorical dtype

TestFilterForStatements (3 tests)
├── Excludes accounts below 61.9 prefix
├── Excludes EXCLUDED_CUENTA (79.1.1.1.01)
├── get_excluded_cuentas returns filtered accounts

TestAssignPartidaPl (7 tests)
├── INGRESOS ORDINARIOS (70.x accounts)
├── COSTO (CECO prefix "1")
├── GASTO VENTA (CECO prefix "2")
├── GASTO ADMIN (CECO prefix "3")
├── D&A - COSTO (CECO prefix "6")
├── RESULTADO FINANCIERO (67.x, 77.x)
└── IMPUESTO A LA RENTA (8x.x)
```

## Testing Patterns Summary

### Pattern 1: Autouse Fixture for State Reset
```python
@pytest.fixture(autouse=True)
def _clear_config_cache():
    get_config.cache_clear()
```

### Pattern 2: Monkeypatch for Environment
```python
def test_smtp_default_on_linux(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("EMAIL_BACKEND", raising=False)
    sender = get_email_sender()
    assert isinstance(sender, SMTPEmailSender)
```

### Pattern 3: tmp_path for File I/O
```python
def test_excel_export(tmp_path, excel_report_data):
    output = tmp_path / "test.xlsx"
    export_to_excel(str(output), 2025, excel_report_data)
    assert output.exists()
    assert output.stat().st_size > 0
```

### Pattern 4: DataFrame Assertion
```python
def test_prepare_pnl_adds_saldo(raw_pnl_df):
    result = prepare_pnl(raw_pnl_df)
    assert "SALDO" in result.columns
    expected = result["CREDITO_LOCAL"] - result["DEBITO_LOCAL"]
    pd.testing.assert_series_equal(result["SALDO"], expected)
```

### Pattern 5: Class-Based Test Grouping
```python
class TestPlRowType:
    def test_blank_row(self): ...
    def test_total_row(self): ...
    def test_subtotal_row(self): ...
    def test_normal_row(self): ...
```

## Coverage Gaps

### Well-Covered Areas
- Data transformation pipeline (prepare → filter → classify)
- PDF helper functions (row filtering, type classification, grouping)
- Email backend selection and config validation
- Aggregation and pivoting functions
- Full pipeline integration (Excel/PDF file creation)

### Areas Needing Tests

| Area | What's Missing | Priority |
|------|---------------|----------|
| CLI (`cli.py`) | Argument parsing, interactive prompts, validation | High |
| Main (`main.py`) | End-to-end workflow, error handling tiers | High |
| Config (`config.py`) | Environment parsing, default values, edge cases | Medium |
| DB Pool (`db.py`) | Connection pooling, thread safety, validation | Medium |
| Excel Styling | Style verification, column widths, formatting | Low |
| PDF Layout | Page breaks, table positioning, font rendering | Low |
| Calendar Config | Period functions, month mappings, edge cases | Low |
| Nota Config | Group iteration, numbering, empty data handling | Low |
| BS Reclassification | Dynamic rules, sign flipping, section overrides | Medium |
| Error Scenarios | Malformed data, missing columns, large datasets | Medium |

## Adding New Tests

### Convention
- Test file: `tests/test_{module_name}.py`
- Test class: `Test{FunctionOrFeature}`
- Test method: `test_{specific_behavior}`
- Use existing fixtures from `conftest.py` when possible

### Example: Adding a Calendar Config Test
```python
# tests/test_calendar_config.py
from calendar_config import get_period_months, get_ytd_months, derive_period_type

class TestGetPeriodMonths:
    def test_month_returns_single_month(self):
        assert get_period_months("month", 6) == [6]

    def test_quarter_returns_three_months(self):
        assert get_period_months("quarter", 2) == [4, 5, 6]

    def test_year_returns_all_months(self):
        assert get_period_months("year", None) == list(range(1, 13))
```
