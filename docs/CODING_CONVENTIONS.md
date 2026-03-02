# Coding Conventions & Patterns

> Standards and patterns used throughout FLXContabilidadEEFF. Follow these when modifying or extending the codebase.

## Python Version & Syntax

- **Minimum Python:** 3.10 (uses PEP 604 union syntax)
- **Type hints:** Modern syntax throughout: `int | None` instead of `Optional[int]`
- **Pattern matching:** Python 3.10+ structural `match/case` used in `excel_export.py`
- **No `from __future__ import annotations`** — uses native 3.10+ typing

## Naming Conventions

### Python Code

| Element | Convention | Example |
|---------|-----------|---------|
| Modules | lowercase_snake_case | `excel_export.py`, `statement_builder.py` |
| Classes | PascalCase | `PnLReportData`, `FinancialPDF`, `EmailSender` |
| Functions (public) | lowercase_snake_case | `export_to_excel()`, `build_pl_rows()` |
| Functions (private) | _prefixed | `_fetch_data()`, `_detail_pivot()` |
| Constants | SCREAMING_SNAKE_CASE | `TOTAL_COL`, `BS_ACCOUNT_PREFIXES`, `HEADER_ROW` |
| Dataclass fields | lowercase_snake_case | `detail_by_cuenta`, `period_type` |
| Logger names | "plantillas.module_name" | `logging.getLogger("plantillas.pipeline")` |

### DataFrame Columns

| Context | Convention | Example |
|---------|-----------|---------|
| From SQL | UPPERCASE_SPANISH | `CUENTA_CONTABLE`, `CENTRO_COSTO`, `DEBITO_LOCAL` |
| Derived columns | UPPERCASE_SPANISH | `SALDO`, `MES`, `PARTIDA_PL`, `SECCION_BS` |
| Month columns | 3-letter English | `JAN`, `FEB`, ..., `DEC` |
| Total column | "TOTAL" | Via `aggregation.TOTAL_COL` constant |
| Intermediate (dropped) | UPPERCASE | `FIRST_CHAR`, `_SECCION_OVERRIDE` |

### Excel Layout Variables

| Variable | Convention | Example |
|----------|-----------|---------|
| Worksheet | `ws` | Common abbreviation |
| ExcelWriter | `writer` | Standard pandas name |
| Sheet name | `sn` or `sheet_name` | Short form in loops |
| Row/column indices | 1-indexed for Excel, 0-indexed for pandas | `HEADER_ROW=4`, `DATA_START_ROW=3` |

## Import Style

### Order (enforced by convention, not tooling)

```python
# 1. Standard library
import logging
import sys
from dataclasses import dataclass, field
from functools import lru_cache

# 2. Third-party
import numpy as np
import pandas as pd
from openpyxl.styles import Font, PatternFill

# 3. Project modules (absolute imports)
from config import get_config
from exceptions import PlantillasError, ConfigurationError
from models import PnLReportData
```

### Key Rules
- **Absolute imports only** — no relative imports (`from .module import`)
- **Explicit `__all__`** in every module — defines public API clearly
- **Lazy imports** where needed — `win32com.client` imported inside methods (platform-specific)
- **dotenv must load before config-dependent imports** — see `main.py` lines 8-9, 20-22

## Module Structure Pattern

Every module follows this structure:

```python
"""Module docstring (if present)."""

__all__ = ["PublicFunction", "PublicClass"]    # 1. Public API declaration

# 2. Imports (stdlib → third-party → project)
import logging
import pandas as pd
from config import get_config

# 3. Module-level logger
logger = logging.getLogger("plantillas.module_name")

# 4. Constants
SOME_CONSTANT = "value"

# 5. Classes / Functions
class MyClass:
    ...

def public_function():
    ...

def _private_helper():
    ...
```

## Error Handling Patterns

### Custom Exception Hierarchy

```python
# Always use semantic exceptions from exceptions.py
raise ConfigurationError("Missing required database configuration")
raise QueryError(f"Failed to fetch data: {exc}") from exc
raise ExportError("Cannot write to file — is it open in another program?")
```

### Exception Chaining
```python
# Preserve context with `from exc`
try:
    conn.execute(sql, params)
except pyodbc.Error as exc:
    raise QueryError(f"Query failed: {exc}") from exc
```

### Handling Tiers
```python
# In main.py: specific → general → fallback
try:
    result = pipeline.run_report(...)
except ConfigurationError:       # Most specific, early exit
    logger.error(...)
    sys.exit(1)
except PlantillasError as exc:   # Catch-all for app errors
    logger.error(f"{type(exc).__name__}: {exc}")
    sys.exit(1)
except Exception:                # Unexpected errors
    logger.exception("Unexpected error")
    sys.exit(1)
```

### Non-Fatal Pattern
```python
# Email failures don't crash the pipeline
try:
    sender.send(file_paths)
except (EmailError, OSError) as exc:
    logger.warning(f"Email failed: {exc}")  # Warning, not error
    # Pipeline continues — files are already generated
```

## Configuration Patterns

### Frozen Dataclass + LRU Cache Singleton
```python
@dataclass(frozen=True)
class Config:
    log_level: str = "INFO"
    db: DatabaseConfig = field(default_factory=DatabaseConfig)

@lru_cache(maxsize=1)
def get_config() -> Config:
    return Config(...)
```

### Environment Variable Reading
```python
# In config.py — centralized, with defaults
os.environ.get("DB_SERVER", "")           # String with empty default
int(os.environ.get("SMTP_PORT", "587"))   # Int with parsed default
os.environ.get("STRICT_BS_BALANCE", "0").lower() in ("1", "true", "yes")  # Bool
```

### Pure Data Configuration Modules
```python
# account_rules.py, company_config.py, calendar_config.py
# NO functions, NO imports from project modules
# Only constants: dicts, tuples, sets, frozensets, lists

DETAIL_CATEGORIES = ["COSTO", "GASTO VENTA", "GASTO ADMIN"]
BS_CLASSIFICATION = {"10": "Efectivo y equivalentes de efectivo", ...}
VALID_COMPANIES = frozenset(COMPANY_META.keys())  # Derived
```

## DataFrame Patterns

### Validation Before Processing
```python
def _validate_columns(df: pd.DataFrame) -> None:
    """Raises DataValidationError if required columns missing."""
    missing = REQUIRED_COLS - set(df.columns)
    if missing:
        raise DataValidationError(f"Missing columns: {missing}")
```

### Copy Before Mutation
```python
df = df.copy()  # Avoid SettingWithCopyWarning
df["SALDO"] = df["CREDITO_LOCAL"] - df["DEBITO_LOCAL"]
```

### Categorical Columns (Memory Optimization)
```python
df["CENTRO_COSTO"] = df["CENTRO_COSTO"].astype("category")
df["PARTIDA_PL"] = pd.Categorical(result, categories=all_partidas)
```

### Vectorized Classification (np.select)
```python
# Prefer np.select() over row-by-row loops
conditions = [
    df["CUENTA_CONTABLE"].isin(SPECIAL_ACCOUNTS),
    df["FIRST_CHAR"] == "7",
    df["CECO_PREFIX"].isin(("1", "4")),
]
choices = ["SPECIAL", "FINANCIAL", "COST"]
result = np.select(conditions, choices, default="UNDEFINED")
```

### Pivot Table Pattern
```python
pivot = pd.pivot_table(
    df,
    values="SALDO",
    index=index_cols,
    columns="MES",
    aggfunc="sum",
    fill_value=0,
    observed=True,        # Only categorical values present in data
).reset_index()
```

## Export Patterns

### Excel: Write First, Style Later
```python
# 1. Write all data to sheets (unstyled)
df.to_excel(writer, sheet_name=sn, startrow=DATA_START_ROW, ...)

# 2. Apply styling in batch at the end
style_init(ws, col_b_width=COL_B_WIDTH_PL)
apply_number_format(ws)
style_pl_sheet(ws)
```

### PDF: DataFrame → Row Dicts → Render
```python
# 1. Convert DataFrame to intermediate representation
rows = _df_to_rows(df, label_cols=["CUENTA_CONTABLE", "DESCRIPCION"], value_cols=col_names)

# 2. Filter and classify
rows = _drop_zero_rows(rows)

# 3. Render to PDF
_render_table(pdf, rows, col_headers, value_headers, ...)
```

### Row Dictionary Structure (PDF)
```python
{
    "labels": ["70.1.1.1.01", "Ventas locales"],   # Label cell values
    "nums": ["1,234,567", "(500,000)", "—"],        # Formatted numbers
    "row_type": "normal"    # "blank" | "group_header" | "normal" | "subtotal" | "total" | "final_total"
}
```

## Concurrency Patterns

### ThreadPoolExecutor for DB Queries
```python
with ThreadPoolExecutor(max_workers=5) as pool:
    futures = {
        pool.submit(_fetch_with_own_conn, "pnl", company, year, month): "pnl",
        pool.submit(_fetch_with_own_conn, "bs", company, year, month): "bs",
    }
    for future in as_completed(futures):
        label = futures[future]
        result = future.result()  # Raises if thread raised
```

### Each Thread Gets Own Connection
```python
def _fetch_with_own_conn(query_type, ...):
    """Thread-safe: creates own connection from pool."""
    with db.connect() as conn:
        return queries.fetch_pnl_data(conn, ...)
```

## Testing Patterns

### Fixture-Based Setup
```python
@pytest.fixture
def raw_pnl_df():
    """Minimal DataFrame mimicking fetch_pnl_data output."""
    return pd.DataFrame({...})

@pytest.fixture(autouse=True)
def _clear_config_cache():
    """Reset config singleton between tests."""
    get_config.cache_clear()
```

### Monkeypatch for Environment
```python
def test_smtp_backend(monkeypatch):
    monkeypatch.setenv("EMAIL_BACKEND", "smtp")
    monkeypatch.setenv("EMAIL_TO", "test@example.com")
    sender = get_email_sender()
    assert isinstance(sender, SMTPEmailSender)
```

### File I/O with tmp_path
```python
def test_excel_export(tmp_path, excel_report_data):
    output = tmp_path / "test.xlsx"
    export_to_excel(str(output), 2025, excel_report_data)
    assert output.exists()
```

## Anti-Patterns to Avoid

1. **Row-by-row DataFrame iteration** — Always use vectorized operations (`np.select`, `pivot_table`, `groupby`)
2. **Mutable default arguments** — Use `field(default_factory=dict)` in dataclasses
3. **Relative imports** — Project uses absolute imports exclusively
4. **Implicit public API** — Always define `__all__` in modules
5. **String-based type checking** — Use `isinstance()` or enums, not string comparisons for types
6. **Silent failures** — Log warnings for non-fatal issues, raise exceptions for fatal ones
7. **Shared pyodbc connections across threads** — Each thread must get its own connection
