# Data Pipeline Audit — 2026-03-30

## Executive Summary

The data pipeline is **well-architected and efficient** for its use case. The three-layer caching strategy, concurrent query execution, and cache reuse between dashboard and exports eliminate most redundant work. This audit documents the full data flow, confirms no accounting logic leaks into the UI layer, and identifies areas for monitoring.

---

## 1. Query Efficiency Analysis

### How Data Is Fetched

**Source**: Single SQL Server view — `REPORTES.VISTA_ANALISIS_CECOS`

**Query Construction** (`data/queries.py`):
- Parameterized queries only (SQL injection-safe)
- Account prefix filtering uses `LIKE ?` (SARGable — index-seekable)
- Date range uses `FECHA >= ? AND FECHA < ?` (SARGable)
- Closing entry exclusion: `FUENTE NOT LIKE 'CIERRE%'`
- SQL identifiers validated at import time via regex (no injection through constants)

### Concurrent Execution (`data/fetcher.py`)

Dashboard load (`need_pdf=False`) submits **2 queries** in parallel:
1. P&L full year (classes 6,7,8) — single query, month-filtered in-memory
2. BS cumulative (classes 1-5) — single query from Jan 1 through period end

Export (`need_pdf=True`) submits up to **4 queries** in parallel:
1. P&L current year (full)
2. P&L previous year (or disk cache)
3. BS current year
4. BS previous year (or disk cache)

Each thread gets its own connection from the pool (thread-safe).

### What's Good

| Area | Implementation | Verdict |
|------|----------------|---------|
| **Connection pooling** | Queue-based pool (default 8), lazy init, health checks (`SELECT 1`) | Efficient |
| **Concurrent queries** | ThreadPoolExecutor (5 workers), independent connections | Efficient |
| **Parameterized SQL** | All user inputs go through `params=` | Secure + cache-friendly for SQL Server |
| **SARGable filters** | `LIKE '6%'` prefix, date range with `>=` and `<` | Index-usable |
| **Previous-year disk cache** | CSV files with 30-day TTL | Eliminates 2 DB round-trips for exports |
| **In-memory cache** | 30-min TTL, LRU (20 entries), thread-safe | Fast dashboard reloads |
| **Export reuse** | Dashboard load caches raw DFs; export skips DB entirely | Eliminates redundant fetches |
| **need_pdf=False** | Web API skips previous-year queries entirely | 50% fewer DB queries for dashboard |

### Design Decisions to Be Aware Of

**1. Full-year P&L fetch + in-memory month filter**
- The pipeline fetches the full year of P&L data and filters months in-memory using pandas
- **Why this is correct**: The full-year data is needed for the 12-month summary view. Fetching per-month would require 12 separate queries. A single query returning all months is more efficient than 12 roundtrips
- **Trade-off**: Slightly more data transferred per query, but only one roundtrip

**2. Whitespace trimming in Python, not SQL**
- `CUENTA_CONTABLE` and `CENTRO_COSTO` are stripped in `_clean_columns()`, not in the SQL query
- Comment in code: "LTRIM/RTRIM removed — whitespace trimming should be handled in the ETL or directly in the SQL view"
- **Why this is correct**: Applying `LTRIM/RTRIM` in the WHERE clause would make filters non-SARGable. Doing it in Python after fetch is the right call

**3. No incremental/delta updates**
- Each load regenerates the full report from raw data
- **Why this is acceptable**: The data source is a SQL Server view that could change at any time. Partial updates would risk inconsistency. The 30-min cache prevents redundant recomputation

**4. pyodbc.pooling = True**
- ODBC-level pooling is enabled globally (off by default on Linux)
- Works in conjunction with the application-level Queue pool for double-layered connection reuse

---

## 2. Transform Efficiency Analysis

### P&L Transform Pipeline

```
raw DataFrame
  → _clean_columns() — copy, strip, extract FIRST_CHAR/MES, parse FECHA, category dtype
  → prepare_pnl() — SALDO = CREDITO - DEBITO
  → filter_for_statements() — prefix >= 619, exclude "79.1.1.1.01"
  → assign_partida_pl() — np.select (single vectorized pass, 14 rules)
  → preaggregate() — groupby at finest grain (PARTIDA, CECO, CUENTA, MES)
  → pivot_by_month() — pivot table with month columns
  → pl_summary() / detail pivots
```

**Efficient patterns**:
- `np.select()` for classification — single vectorized pass instead of iterating rows
- `pd.Categorical` for PARTIDA_PL, CENTRO_COSTO, SECCION_BS — reduced memory
- `preaggregate()` computes finest-grain groupby once; all detail pivots reuse it
- `pivot_by_month()` ensures all 12 months exist via `reindex(fill_value=0)` — avoids downstream null checks

### BS Transform Pipeline

```
raw DataFrame
  → _clean_columns() — same as P&L
  → prepare_bs() — SALDO with sign logic (Assets: D-C, Liabilities: C-D)
  → assign_partida_bs() — np.select for overrides, prefix-2 map for base, fallback by FIRST_CHAR
  → bs_summary() — pivot, cumsum, reclassification, Resultados del Ejercicio injection
```

**Efficient patterns**:
- BS override rules sorted by prefix length at module load (`_SORTED_BS_OVERRIDES`) — avoids repeated sorting
- `_apply_bs_cumsum()` applies cumulative sum in-place on all 12 months at once
- Reclassification and sign-flip logic handles cross-section overrides in a single pass

### JSON Serialization

- `_sanitize_value()` handles all numpy/pandas edge cases (np.integer, np.floating, np.nan, np.bool_)
- `_df_to_records()` uses `df.to_dict(orient="records")` + sanitization — efficient for the data sizes involved

---

## 3. Caching Strategy Assessment

### Layer 1: In-Memory Cache (data_service.py)

| Property | Value | Assessment |
|----------|-------|------------|
| TTL | 30 minutes | Appropriate for financial data that updates periodically |
| Max entries | 20 per store | 4 companies × 5 years = 20 — covers typical usage |
| Eviction | LRU (OrderedDict) | Correct for access-pattern-based eviction |
| Thread safety | threading.Lock | Correct for Gunicorn sync workers (separate processes) |
| Stores | 4 (result, df, bs, raw) | Enables selective reuse (exports reuse raw/bs without regenerating) |
| Invalidation | `invalidate_cache()` + `force_refresh=True` | User can force fresh data when needed |

### Layer 2: Export Reuse (routes.py)

- `_run_export()` checks `get_raw_cached()` and `get_bs_cached()` before calling the pipeline
- If dashboard was loaded within 30 minutes, export skips DB entirely
- **Result**: Typical workflow (view dashboard → export) executes 0 additional DB queries

### Layer 3: Disk Cache (data/.cache/)

| Property | Value | Assessment |
|----------|-------|------------|
| TTL | 30 days | Historical data rarely changes; generous but safe |
| Format | CSV | Simple, debuggable, small overhead for these data sizes |
| Scope | Previous-year P&L + BS only | Current year always fetched fresh |
| Error handling | Corrupted files silently skipped (re-fetched) | Resilient |

---

## 4. Frontend Data Handling Assessment

### What the Frontend Does (Correct — Presentation Only)

1. **Column building**: Maps months to display columns (monthly/quarterly/trailing 12M)
2. **Data merging for trailing 12M**: Picks values from current or previous year per month — no computation
3. **Cell value computation**: Sums pre-computed monthly values for quarterly P&L, or uses last-month balance for quarterly BS
4. **Formatting**: Spanish locale (`es-PE`), 2 decimal places
5. **Pagination**: Client-side on already-fetched detail records

### What the Frontend Does NOT Do (Correct — No Accounting Logic)

- No gross profit / operating profit / net income computation
- No account reclassification or sign changes
- No cumulative sum logic
- No journal entry processing
- No balance sheet equation validation

**Verdict**: The frontend is a pure presentation layer. All accounting logic stays in the Python backend.

---

## 5. Connection Management Assessment

### Pool Architecture

```
pyodbc.pooling = True          ← ODBC driver-level pooling (reuses OS handles)
    └── Application pool       ← Queue(maxsize=8) with health checks
        └── Per-thread conn    ← ThreadPoolExecutor threads each get own connection
```

### Pool Behavior

| Scenario | Behavior |
|----------|----------|
| Connection available in pool | Reuse (after `SELECT 1` health check) |
| Pool empty | Create new connection |
| Connection stale | Discard + create new |
| Error during use | Close connection (don't return to pool) |
| Pool full on return | Close connection |
| Gunicorn worker restart | Pool recreated (per-process) |

### Timeouts

| Timeout | Default | Purpose |
|---------|---------|---------|
| `DB_CONNECT_TIMEOUT` | 30s | Initial connection establishment |
| `DB_QUERY_TIMEOUT` | 120s | Per-query execution limit |
| `_FUTURE_TIMEOUT` | 120s | ThreadPoolExecutor future collection |
| `GUNICORN_TIMEOUT` | 120s | Worker request timeout |

**Note**: The query timeout (120s) matches the Gunicorn timeout (120s). This is intentional — a query that exceeds this is likely hung and should be killed rather than blocking the worker.

---

## 6. Recommendations

### No Action Required (Already Optimal)

1. **Concurrent queries** — Already parallelized with ThreadPoolExecutor
2. **Cache reuse** — Dashboard → Export flow already skips DB
3. **need_pdf=False** — Web API already skips unnecessary queries
4. **Vectorized transforms** — np.select, pd.pivot_table, reindex are already optimal
5. **Pre-aggregation** — Finest-grain groupby computed once, reused by all detail pivots
6. **Category dtypes** — CENTRO_COSTO and classification columns use memory-efficient categories

### Monitor (No Code Changes, Just Awareness)

1. **Data volume growth**: If row counts per query grow significantly (currently 500–5000 per company/year for P&L), monitor `data_service.py` timing logs (`"Data fetch: %.2fs"`, `"Transforms: %.2fs"`)
2. **Cache hit rate**: Consider adding a cache-hit counter if you suspect the 30-min TTL is too short for your usage patterns
3. **Disk cache size**: The `data/.cache/` directory grows with (companies × years). With 4 companies and a few years, this is negligible. No cleanup mechanism is needed yet

### Optional Future Improvements (Not Urgent)

1. **SQL Server index review**: Verify that `VISTA_ANALISIS_CECOS` has covering indexes on `(CIA, FECHA, CUENTA_CONTABLE)` — this would maximize the SARGable query performance
2. **Gzip compression**: Consider enabling gzip in nginx for API responses — the JSON payloads (12 months × 20+ rows × multiple detail tables) compress well
3. **Response size monitoring**: The `/api/data/load` response includes all detail tables. If response size becomes a concern, detail tables could be lazy-loaded (fetched on view switch, not on initial load)

---

## 7. Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│  SQL Server (REPORTES.VISTA_ANALISIS_CECOS)                 │
└──────────────────────┬──────────────────────────────────────┘
                       │ pyodbc (pooled, parameterized)
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  data/fetcher.py — ThreadPoolExecutor (5 workers)           │
│  ┌─────────────┐  ┌─────────────┐                           │
│  │ P&L current │  │ BS current  │  ← Dashboard: 2 queries   │
│  └─────────────┘  └─────────────┘                           │
│  ┌─────────────┐  ┌─────────────┐                           │
│  │ P&L prev    │  │ BS prev     │  ← Export: +2 (or cache)  │
│  └──────┬──────┘  └──────┬──────┘                           │
│         └── disk cache ──┘  (30-day TTL)                    │
└──────────────────────┬──────────────────────────────────────┘
                       │ pd.DataFrame
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  accounting/ — SACRED LOGIC (do not modify)                 │
│                                                             │
│  transforms.py:                                             │
│    prepare_pnl() → SALDO = CREDITO − DEBITO                │
│    prepare_bs()  → SALDO with sign by account class         │
│    assign_partida_pl() → np.select (14 rules, priority)     │
│    assign_partida_bs() → overrides + 2-digit prefix map     │
│                                                             │
│  statements.py:                                             │
│    pl_summary() → hierarchical P&L with subtotals           │
│    bs_summary() → sections, cumsum, reclassification,       │
│                   Resultados del Ejercicio injection         │
│                                                             │
│  aggregation.py:                                            │
│    preaggregate() → finest-grain groupby (computed once)     │
│    pivot_by_month() → 12-month pivot with fill              │
│    detail_by_ceco/cuenta → reuse preaggregate               │
└──────────────────────┬──────────────────────────────────────┘
                       │ dict of DataFrames → JSON
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  data_service.py — In-Memory Cache (30-min TTL, LRU)        │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│  │ result   │ │ df_stmt  │ │ df_bs    │ │ raw      │       │
│  │ (JSON)   │ │ (P&L DF) │ │ (BS DF)  │ │ (raw DFs)│       │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘       │
│  ▲ dashboard   ▲ drill-down  ▲ export    ▲ export          │
└──────────────────────┬──────────────────────────────────────┘
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
    /api/data/load  /api/data/   /api/export/*
     (full report)   detail       (reuses cache)
          │         (drill-down)        │
          ▼            ▼                ▼
┌─────────────────────────────────────────────────────────────┐
│  Frontend (React) — PRESENTATION ONLY                       │
│                                                             │
│  ReportContext:                                              │
│    buildDisplayColumns() → monthly/quarterly/trailing12M     │
│    mergeTrailingRows()   → pick values from correct year     │
│                                                             │
│  FinancialTable:                                            │
│    getCellValue() → sum sourceMonths (P&L) or last (BS)     │
│    formatNumber() → es-PE locale                            │
│                                                             │
│  PLNoteView / DetailTable:                                  │
│    drill-down → POST /api/data/detail                       │
│    pagination, filtering on fetched records                  │
└─────────────────────────────────────────────────────────────┘
```
