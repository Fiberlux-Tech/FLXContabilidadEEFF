# Data Flow & Transformations

> How data moves from SQL Server through the pipeline to Excel/PDF output.

## End-to-End Data Pipeline

```
SQL Server (REPORTES.VISTA_ANALISIS_CECOS)
    │
    ▼
queries.fetch_pnl_data() / fetch_bs_data()
    │  Raw pd.DataFrame with GL entry columns
    ▼
transforms.prepare_pnl() / prepare_bs()
    │  Cleaned DataFrame (+ SALDO, MES, FIRST_CHAR)
    ▼
transforms.assign_partida_pl() / assign_partida_bs()
    │  Classified DataFrame (+ PARTIDA_PL/BS, SECCION_BS)
    ▼
aggregation.preaggregate()          [optional, performance optimization]
    │
    ├──▶ aggregation.detail_*()     → Pivoted by month (Excel)
    ├──▶ aggregation.summarize_*()  → Summary views (Excel)
    ├──▶ statement_builder.*()      → P&L/BS structured rows (Excel + PDF)
    └──▶ pdf_reports.*_pdf()        → Period-aware columns (PDF)
    │
    ▼
models.PnLReportData / PdfReportData
    │
    ├──▶ excel_export.export_to_excel()
    └──▶ pdf_export.export_to_pdf()
```

## Stage 1: Data Extraction (queries.py)

### SQL Source
- **Schema:** `REPORTES`
- **View:** `VISTA_ANALISIS_CECOS` (pre-calculated analysis view)
- **Whitespace trimming:** Done in the SQL view, not per-query

### Fetched Columns

| Column | Type | Description |
|--------|------|-------------|
| `CIA` | str | Company code |
| `CUENTA_CONTABLE` | str | Account code (hierarchical, e.g., "70.1.1.1.01") |
| `DESCRIPCION` | str | Account description |
| `NIT` | str | Related party tax ID |
| `RAZON_SOCIAL` | str | Related party name |
| `CENTRO_COSTO` | str | Cost center code |
| `DESC_CECO` | str | Cost center description |
| `FECHA` | datetime | Transaction date |
| `DEBITO_LOCAL` | float | Debit amount (local currency) |
| `CREDITO_LOCAL` | float | Credit amount (local currency) |

### Query Strategies

| Function | Account Prefixes | Date Logic | Purpose |
|----------|-----------------|------------|---------|
| `fetch_pnl_data()` | "6", "7", "8" | Period-specific (non-cumulative) | Income statement accounts |
| `fetch_bs_data()` | "1", "2", "3", "4", "5" | Cumulative from Jan 1 | Balance sheet accounts |

### SQL Parameterization
- Account filtering: `LEFT(CUENTA_CONTABLE, 1) IN (?, ?, ...)`
- Date ranges: `FECHA BETWEEN ? AND ?`
- All parameters use pyodbc parameterized queries (injection-safe)

## Stage 2: Data Cleaning (transforms.py)

### prepare_pnl() Pipeline
```
1. _validate_columns(df)     → Ensures required columns exist
2. _clean_columns(df)        → Adds FIRST_CHAR, parses FECHA, extracts MES
3. Compute SALDO             → CREDITO_LOCAL - DEBITO_LOCAL
```

### prepare_bs() Pipeline
```
1. _validate_columns(df)     → Same validation
2. _clean_columns(df)        → Same cleaning
3. Compute SALDO (context-sensitive):
   - Assets (FIRST_CHAR 1-3): DEBITO_LOCAL - CREDITO_LOCAL
   - Liabilities/Equity (4-5): CREDITO_LOCAL - DEBITO_LOCAL
```

### Derived Columns After Cleaning

| Column | Source | Description |
|--------|--------|-------------|
| `FIRST_CHAR` | `CUENTA_CONTABLE[0]` | First character, used for classification rules |
| `FECHA` | Parsed datetime | Converted from date string |
| `MES` | `FECHA.dt.month` | Month number (1-12) |
| `CENTRO_COSTO` | Categorical conversion | Memory optimization |
| `SALDO` | Computed | Balance amount (sign depends on account type) |

## Stage 3: Classification (transforms.py)

### P&L Classification (assign_partida_pl)

Uses `np.select()` vectorized operation with 14 rules in priority order (first match wins):

| Priority | Rule | PARTIDA_PL Value |
|----------|------|------------------|
| 1 | Account in PROVISION_INCOBRABLE_CUENTAS | "PROVISION INCOBRABLE" |
| 2 | CECO prefix "6" | "D&A - COSTO" |
| 3 | Account prefix in DYA_GASTO_PREFIXES (68.0-68.6) | "D&A - GASTO" |
| 4 | Account = PARTICIPACION_TRABAJADORES_CUENTA | "PARTICIPACION DE TRABAJADORES" |
| 5 | Account prefix in DIFERENCIA_CAMBIO (67.6, 77.6) | "DIFERENCIA DE CAMBIO" |
| 6 | Account prefix in RESULTADO_FINANCIERO (67, 77) | "RESULTADO FINANCIERO" |
| 7 | Account prefix = "70" | "INGRESOS ORDINARIOS" |
| 8 | Account = INGRESOS_PROYECTOS_CUENTA | "INGRESOS PROYECTOS" |
| 9 | Account prefix in OTROS_INGRESOS (73, 75) | "OTROS INGRESOS" |
| 10 | First char = "8" | "IMPUESTO A LA RENTA" |
| 11 | CECO prefix "7" | "RESULTADO FINANCIERO" |
| 12 | CECO prefix "1" or "4" | "COSTO" |
| 13 | CECO prefix "2" | "GASTO VENTA" |
| 14 | CECO prefix "3" | "GASTO ADMIN" |
| default | None matched | "POR DEFINIR" (logged as warning) |

All classification rules are defined in `account_rules.py` as constants.

### BS Classification (assign_partida_bs)

Two-phase process:
1. **Override check:** Iterate `BS_CLASSIFICATION_OVERRIDES` (longest prefix first)
2. **Default:** Map 2-digit prefix via `BS_CLASSIFICATION` dict

Creates two columns:
- `PARTIDA_BS` — Line item label (e.g., "Efectivo y equivalentes de efectivo")
- `SECCION_BS` — Section: "ACTIVO", "PASIVO", or "PATRIMONIO"

### Account Filtering (filter_for_statements)

Removes accounts before pivoting:
- Accounts with prefix < "61.9" (blocks lower P&L accounts)
- Specifically excludes account "79.1.1.1.01"
- Excluded accounts tracked in `PnLReportData.excluded_cuentas`

## Stage 4: Aggregation (aggregation.py)

### Core Pivot Function

`pivot_by_month(df, index_cols, add_total=True)`:
- Uses `pd.pivot_table()` with `SALDO` as values, `MES` as columns
- Replaces numeric months (1-12) with names ("JAN", "FEB", ..., "DEC")
- `fill_value=0` for missing month/category combinations
- `observed=True` filters to categorical values present in data
- Optionally appends `TOTAL` column (sum across months)

### Aggregation Levels

| Function | Index Columns | Use Case |
|----------|--------------|----------|
| `summarize_by_cuenta()` | CUENTA_CONTABLE, DESCRIPCION | Account-level summary |
| `summarize_by_ceco()` | CENTRO_COSTO, DESC_CECO | Cost center summary |
| `summarize_by_ceco_cuenta()` | CENTRO_COSTO, CUENTA_CONTABLE | Most granular pre-agg |
| `detail_by_ceco()` | CENTRO_COSTO, DESC_CECO (filtered by PARTIDA_PL) | Expense breakdown by CC |
| `detail_by_cuenta()` | CUENTA_CONTABLE, DESCRIPCION (filtered) | Detail by account |
| `detail_ceco_by_cuenta()` | CENTRO_COSTO, DESC_CECO, CUENTA_CONTABLE, DESCRIPCION | Expanded drill-down |
| `sales_details()` | CUENTA_CONTABLE (filtered to INGRESOS ORDINARIOS) | Revenue detail |
| `proyectos_especiales()` | NIT, RAZON_SOCIAL (filtered to INGRESOS PROYECTOS) | Projects by client |
| `bs_detail_by_cuenta()` | CUENTA_CONTABLE, DESCRIPCION (BS with cumsum) | BS account detail |

### Performance Optimization

`preaggregate(df)` pre-groups at the finest grain (PARTIDA_PL + CENTRO_COSTO + DESC_CECO + CUENTA_CONTABLE + DESCRIPCION + MES) and sums SALDO once. All subsequent `detail_*` functions use this pre-aggregated result to avoid redundant groupby.

### Output Column Structure

After pivoting, DataFrames have:
- **Index columns** (varies by aggregation level)
- **Month columns:** "JAN", "FEB", ..., "DEC" (only months with data)
- **TOTAL column:** Sum across all months (when `add_total=True`)

### Balance Sheet Specifics

`bs_detail_by_cuenta()` adds cumulative sum across months (BS is point-in-time, not flow):
1. Pivot by month (no total initially)
2. Ensure all 12 months exist (fill 0)
3. `cumsum()` across month columns
4. Filter to `keep_months` if specified
5. Sort by last month's cumulative value (descending)

### ResultadoFinanciero (Named Tuple)

`split_resultado_financiero()` separates financial results:
- `ingresos`: Accounts with prefix "77" (financial income)
- `gastos`: All other RESULTADO FINANCIERO accounts (financial expenses)

## Stage 5: Statement Building (statement_builder.py)

### P&L Statement Structure (build_pl_rows)

```
INGRESOS ORDINARIOS                    [from lookup]
INGRESOS PROYECTOS                     [from lookup]
─────────────────────────────
INGRESOS TOTALES                       = sum(above)

COSTO                                  [from lookup]
D&A - COSTO                            [from lookup]
─────────────────────────────
UTILIDAD BRUTA                         = INGRESOS_TOTALES + COSTO + D&A_COSTO

GASTO VENTA                            [from lookup]
GASTO ADMIN                            [from lookup]
PARTICIPACION DE TRABAJADORES          [from lookup]
D&A - GASTO                            [from lookup]
PROVISION INCOBRABLE                   [from lookup]
OTROS INGRESOS                         [from lookup]
─────────────────────────────
UTILIDAD OPERATIVA                     = UTILIDAD_BRUTA + sum(above)

RESULTADO FINANCIERO                   [from lookup]
DIFERENCIA DE CAMBIO                   [from lookup]
─────────────────────────────
UTILIDAD ANTES DE IMPUESTO A LA RENTA  = UTILIDAD_OP + sum(above)

IMPUESTO A LA RENTA                    [from lookup]
─────────────────────────────
UTILIDAD NETA                          = UTILIDAD_AIR + IMPUESTO_RENTA
```

All calculations use numpy array operations (vectorized per value column).

### BS Statement Structure (bs_summary)

Organized by section with partida subtotals:
```
ACTIVO
  [partidas in BS_PARTIDA_ORDER]
    [indented account detail: "  {cuenta}  {desc}"]
TOTAL ACTIVO

PASIVO
  [partidas...]
TOTAL PASIVO

PATRIMONIO
  [partidas...]
  Resultados del Ejercicio    [injected from P&L UTILIDAD NETA cumsum]
TOTAL PATRIMONIO

TOTAL PASIVO Y PATRIMONIO
```

### BS Account Reclassification

Three dynamic rules applied before structure building:

| Rule | Condition | Action |
|------|-----------|--------|
| Rule 1 | Account 12.2.1.1.01 is negative | Move to PASIVO as "Anticipos Recibidos" (flip sign) |
| Rule 2 | Prefix "14" accounts are negative | Move to PASIVO as "Provisiones por beneficios..." (flip sign) |
| Rule 3 | Prefix "42.2" accounts are negative | Move to ACTIVO as "Anticipos Otorgados" (flip sign) |

After dynamic rules, a static override flips sign when an account's native section (by first char) differs from its assigned section.

## Stage 6: PDF-Specific Aggregation (pdf_reports.py)

### Column Structure (Period-Aware)

| Period Type | Columns (4 or 2) |
|-------------|-------------------|
| Month | "MONTH YEAR", "MONTH PREV_YEAR", "YTD YEAR", "YTD PREV_YEAR" |
| Quarter | "Q# YEAR", "Q# PREV_YEAR", "YTD YEAR", "YTD PREV_YEAR" |
| Year | "YEAR", "PREV_YEAR" |

### Key Functions

| Function | Output | Notes |
|----------|--------|-------|
| `pl_summary_pdf()` | P&L with 2 or 4 value columns | Uses shared `build_pl_rows()` |
| `bs_summary_pdf()` | BS point-in-time snapshot | 2 columns (current/prev year) |
| `detail_by_ceco_pdf()` | Cost center detail by period | Sorted by default_sort_col |
| `detail_by_cuenta_pdf()` | Account detail by period | Sorted by default_sort_col |
| `sales_details_pdf()` | Revenue detail | INGRESOS ORDINARIOS only |
| `proyectos_especiales_pdf()` | Projects by NIT | With RAZON_SOCIAL grouping |
| `bs_detail_by_cuenta_pdf()` | BS account detail | Cumulative through period |
| `bs_relacionadas_nit_pdf()` | Related-party NIT pivots | Single year |

## Data Model Containers

### PnLReportData (19 DataFrame fields + 1 dict)

```python
@dataclass
class PnLReportData:
    # Summary levels
    detail_by_cuenta: pd.DataFrame
    detail_by_ceco: pd.DataFrame
    detail_by_ceco_cuenta: pd.DataFrame
    pl_summary: pd.DataFrame

    # Partida details (by CECO)
    sales_details: pd.DataFrame
    proyectos_especiales: pd.DataFrame
    costo: pd.DataFrame
    gasto_venta: pd.DataFrame
    gasto_admin: pd.DataFrame

    # Expanded views (by CUENTA within CECO)
    costo_expanded: pd.DataFrame
    gasto_venta_expanded: pd.DataFrame
    gasto_admin_expanded: pd.DataFrame

    # Financial results
    resultado_financiero_ingresos: pd.DataFrame
    resultado_financiero_gastos: pd.DataFrame

    # D&A
    dya_costo: pd.DataFrame
    dya_gasto: pd.DataFrame
    dya_costo_expanded: pd.DataFrame
    dya_gasto_expanded: pd.DataFrame

    # Balance sheet details (populated separately)
    bs_sheets: dict[str, pd.DataFrame]
    excluded_cuentas: set
```

### PdfReportData (subset + metadata)

```python
@dataclass
class PdfReportData:
    company: str
    year: int
    period_type: str
    period_num: int | None
    column_names: tuple          # 4 or 2 value column headers
    bs_details: dict[str, pd.DataFrame]
    nit_pivots: dict[str, tuple[pd.DataFrame, pd.DataFrame]]
    # ... plus summary DataFrames (no expanded views)
```

### PeriodContext (shared parameter bundle)

```python
@dataclass
class PeriodContext:
    df_current: pd.DataFrame
    df_prev: pd.DataFrame
    period_type: str
    period_num: int | None
    year: int
```
