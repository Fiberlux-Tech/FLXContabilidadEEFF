# Coding Patterns & Conventions

## General
- Keep it simple. This is an internal tool, not a SaaS product.
- No over-engineering. Solve the current problem, not hypothetical future ones.
- Spanish for user-facing text. English for code (variable names, comments, docs).

## Python (Backend + Services)

### Style
- Python 3.10+ (uses `int | None` union syntax)
- Type hints on function signatures
- Dataclasses for configuration (`@dataclass(frozen=True)`)
- Context managers for DB connections (`with connect() as conn:`)

### Error Handling
- Custom exception hierarchy in `backend/config/exceptions.py`
- Services raise domain-specific exceptions (`QueryError`, `DataValidationError`)
- Backend catches and returns JSON error responses with appropriate HTTP status codes:
  - 400 for validation errors (`ValueError`, `KeyError`)
  - 404 for missing files
  - 500 for unexpected errors (logged with `logger.exception`)

### Database
- Read-only access to SQL Server via pyodbc
- Parameterized queries only (no string interpolation in SQL)
- Connection per request/thread (pyodbc connections are not thread-safe)
- Concurrent queries via `ThreadPoolExecutor` with separate connections per thread

### Configuration — Layered .env Loading
- `backend/config/env_loader.py` loads environment in two steps:
  1. `.env` at monorepo root (shared defaults, `override=False`)
  2. `.env.{APP_ENV}` (environment-specific overrides, `override=True`)
- `APP_ENV` defaults to `production` if not set
- `get_config()` returns a frozen dataclass, cached with `@functools.lru_cache`
- All secrets and connection strings come from env vars, never hardcoded

### Import Path Setup
- `backend/app.py` adds `backend/` and `backend/services/` to `sys.path`
- This allows bare imports: `from config.settings import ...`, `from data.fetcher import ...`
- All Python packages (config, data, models, services, accounting) live inside `backend/`

### Caching
Three cache layers, each with a specific role:

**In-memory cache** (`data_service.py`):
- Keyed by `(company, year)` tuples
- 30-minute TTL (`MEMORY_CACHE_TTL = 1800`), bounded to 20 entries per store (LRU eviction)
- Thread-safe via `threading.Lock`
- Four separate stores (OrderedDict): result dict, raw DataFrames, prepared BS, statement DataFrame
- `force_refresh=True` bypasses the cache

**File-based previous-year cache** (`backend/data/.cache/`):
- CSV files with 30-day TTL
- Previous-year P&L/BS data changes rarely, so this avoids repeated DB round-trips

### DataFrame → JSON Sanitization
- `_sanitize_value()` converts numpy/pandas types to JSON-safe Python types
- `np.integer` → `int`, `np.floating` → `round(float, 2)`, `np.nan` → `None`, `np.bool_` → `bool`
- `_df_to_records()` applies this to every cell before returning to the API

### Month Column Ordering
- `MONTH_NAMES_LIST` (in `backend/config/calendar.py`) is the single source of calendar-ordered month names
- Use `reindex(columns=non_month_cols + MONTH_NAMES_LIST, fill_value=0)` to ensure all 12 month columns exist in order
- Never reconstruct via `list(MONTH_NAMES.values())` — import `MONTH_NAMES_LIST` instead

### Account Classification Rules
- **P&L classification lives in SQL** (`REPORTES.VISTA_PNL_PREPARADO`) as of Phase A — priority-ordered `CASE WHEN` in the view supplies `PARTIDA_PL` and `IS_INTERCOMPANY` directly. Edit the view's CASE blocks (all four per-CIA views) to change rules.
- **BS classification still lives in Python** (`backend/services/accounting/rules.py` + `assign_partida_bs()` in `transforms.py`) — np.select with priority-ordered conditions, BS_CLASSIFICATION + BS_CLASSIFICATION_OVERRIDES. Will move to `VISTA_BS_PREPARADO` in Phase B.
- Cost-center first character determines cost vs. sales expense vs. admin expense (encoded in the view's CASE for P&L; in rules.py for BS).
- BS classification maps account prefixes → statement line items, with per-account overrides.
- Account prefix parsing in Python uses `_cuenta_prefix(s, n)` (first n chars of dotted code) in `transforms.py`.

### Accounting Logic — SACRED, DO NOT MODIFY

The accounting transformation pipeline is the core of this system. Its logic must NEVER be altered by UI changes, refactoring, or "improvements" unless explicitly requested for accounting correctness reasons.

**Protected modules** (changes require explicit accounting justification):
- `backend/services/accounting/rules.py` — BS classification constants, BS reclassification rules, display order, P&L display helpers (subtotal labels, detail categories). P&L row-level classification lives in the SQL view; this module no longer holds those constants.
- `backend/services/accounting/transforms.py` — SALDO computation for BS (sign by account class), BS partida assignment (np.select priority order), and the dtype adapter `prepare_pnl_from_view` that shapes view rows for downstream aggregation. P&L SALDO / filtering / partida assignment all moved to the SQL view in Phase A.
- `backend/services/accounting/statements.py` — P&L row structure (subtotal formulas: UTILIDAD BRUTA, OPERATIVA, NETA), BS row structure (CORRIENTE/NO CORRIENTE split, reclassification, Resultados del Ejercicio injection), balance validation (ACTIVO = PASIVO + PATRIMONIO)
- `backend/services/accounting/aggregation.py` — Pivot logic (monthly sums, cumsum for BS), period aggregation, resultado financiero split (prefix "77" = ingresos)
- `backend/data/queries.py` — SQL query construction (reads `VISTA_PNL_PREPARADO` for P&L; raw `VISTA_ANALISIS_CECOS` for BS), date range logic, closing entry exclusion
- `sql/VISTA_PNL_PREPARADO.sql` — SQL view in `[FIBERLINE|FIBERTECH|NEXTNET|FIBERLUX].VISTA_PNL_PREPARADO` that owns P&L row-level classification (SALDO, MES, PARTIDA_PL, IS_INTERCOMPANY, IS_STATEMENT_ELIGIBLE). **Single source of truth** for P&L classification rules since Phase A Step 4. Editing the CASE blocks must be done in **all four per-CIA views**; validate by running `sql/PARITY_CHECKS.sql` and eyeballing dashboard totals against Excel for a known-good month. The Python-side parity harness was deleted in Phase A Step 4 — see [SQL_VIEWS_ROADMAP.md](SQL_VIEWS_ROADMAP.md) "Drift mitigation" for the current posture.
- `sql/VISTA_BS_PREPARADO.sql` — DDL committed, not yet deployed; will own BS classification once Phase B ships. See [sql/README.md](../sql/README.md) for topology.

**Sacred invariants** (must hold true at all times):
1. P&L SALDO = CREDITO_LOCAL − DEBITO_LOCAL (never reversed)
2. BS SALDO: Assets (1,2,3) = DEBITO − CREDITO; Liabilities/Equity (4,5) = CREDITO − DEBITO
3. BS accounts with negative cumulative balance are reclassified per BS_RECLASSIFICATION_RULES (sign flipped on section change)
4. Cross-section overrides (native section ≠ assigned section) flip sign automatically
5. P&L PARTIDA assignment in `VISTA_PNL_PREPARADO` is priority-ordered (CASE WHEN); first matching condition wins, just like the np.select it replaced. Rule order is intentional — edits must preserve priority semantics. BS PARTIDA assignment in `assign_partida_bs()` uses np.select with the same priority discipline.
6. Year-end closing entries (FUENTE LIKE 'CIERRE%') are always excluded from both P&L and BS
7. P&L shows monthly flows; BS shows cumulative balances (cumsum applied)
8. "Resultados del Ejercicio" in PATRIMONIO = cumulative UTILIDAD NETA from P&L
9. BS must balance: TOTAL ACTIVO = TOTAL PASIVO + TOTAL PATRIMONIO

**What the frontend may do** (presentation-only):
- Sum pre-computed monthly values for quarterly display
- Use last month's balance for quarterly BS (not sum)
- Merge current + previous year rows for trailing 12M display
- Format numbers, apply styles, filter/paginate

**What the frontend must NEVER do**:
- Compute gross profit, operating profit, net income, or any accounting subtotals
- Reclassify accounts or change signs
- Apply cumulative sums or balance sheet logic
- Override or modify backend-computed values

### Security Patterns
- **Input validation**: `_validate_company_year()` shared helper validates company against allowlist and year range
- **Column filtering allowlist**: Detail drill-down only allows filtering on explicitly listed columns (`_FILTERABLE_COLUMNS` in `backend/services/data_service.py`)
- **Rate limiting**: Failed login attempts are rate-limited per IP
- **Session cookies**: HttpOnly, SameSite=Lax

### Logging
- Named loggers per module: `logging.getLogger("flxcontabilidad.routes")`
- Services use `"plantillas.*"` namespace (legacy from CLI tool)
- `LOG_LEVEL` env var controls verbosity (default: `INFO`)
- Performance timing with `time.perf_counter()` logged at INFO level

## TypeScript (Frontend)

### Style
- React functional components only
- TypeScript strict mode
- Tailwind CSS for styling (no CSS modules, no styled-components)
- Path alias: `@/` maps to `src/`

### State Management
- `AuthContext`: user state + logout callback
- `ReportContext`: `useReducer`-based state machine managing:
  - Selection state: company, year, granularity (`monthly` | `quarterly`), periodRange (`ytd` | `trailing12`)
  - Data state: reportData (current year), prevYearData (for trailing 12M), loading/error
  - View state: currentView (which report panel is active)
  - Display helpers: `getDisplayColumns(variant)`, `getMergedRows()`, `getMergedDetailRows()`
- `useMemo` / `useCallback` for computed values (display columns, trailing month sources)
- Debounced auto-load (300ms) with `AbortController` cancellation on rapid changes
- No Redux, no Zustand — keep it simple

### API Calls
- All HTTP requests go through `src/lib/api.ts`
- Centralized error handling (throws on non-200)
- Cookies included automatically (`credentials: 'include'`)
- Generic typed methods: `api.get<T>()`, `api.post<T>()`, `api.postForm<T>()`

### Auth Pattern
- `checkAuthStatus()` on app mount → set user or redirect to login
- `loginUser()` → sets cookie, returns user data
- `logoutUser()` → clears session
- `useAuth()` hook for accessing current user anywhere

### Component Hierarchy
```
App.tsx (auth check → login or dashboard)
├── AuthProvider
│   └── ReportProvider
│       └── DashboardShell
│           ├── TopBar (company selector, year selector, granularity toggle, period range toggle, current-view Excel export)
│           ├── Sidebar (view navigation)
│           └── MainContent (view switching)
│               ├── FinancialTable (P&L or BS summary — shared component)
│               ├── DetailTable (detail rows by CECO/cuenta with drill-down)
│               └── PLNoteView (P&L detail views: ingresos, costo, gasto, D&A, resultado financiero)
```

### File Organization
```
src/
├── App.tsx              # Root component (auth check + layout)
├── main.tsx             # Entry point
├── index.css            # Tailwind imports
├── lib/                 # Utilities (api client)
├── config/              # Constants, endpoints
├── types/               # TypeScript interfaces (ReportData, DisplayColumn, MonthSource, etc.)
├── contexts/            # AuthContext, ReportContext (useReducer + display logic)
├── components/          # Shared components (ErrorBoundary)
└── features/
    ├── auth/            # Login page + auth service
    └── dashboard/       # DashboardShell, TopBar, Sidebar, MainContent,
                         # FinancialTable, DetailTable, PLNoteView
```

### Export Pattern
- Exporting the current view is fully client-side: `useViewExport` reads the active report state from `ReportContext`, builds sheet definitions per view, and SheetJS produces the `.xlsx` in the browser.
- The backend does not participate in exports — no `/api/export/*` endpoint exists.

## Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for the staging + prod workflow, the `deploy.sh` script, environment layout, firewall rules, and agent-facing rules. Don't run `npm run build` / `systemctl restart` manually — always go through `./deploy.sh` so the deploy is reproducible and logged.

### Create Users
```bash
cd backend
../venv/bin/python manage.py create-user --username john --password secret123
../venv/bin/python manage.py list-users
../venv/bin/python manage.py reset-password --username john --password newpass
../venv/bin/python manage.py delete-user --username john
```
Run these in the **staging tree only** if you're adding a non-admin test account — never mirror prod users to staging (see DEPLOYMENT.md).
