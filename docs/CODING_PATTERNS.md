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
- Services raise domain-specific exceptions (`QueryError`, `ExportError`, `DataValidationError`)
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

**Export reuse**:
- When exporting, `_run_export()` checks `get_raw_cached()` and `get_bs_cached()`
- If dashboard was loaded recently, export skips DB entirely and reuses cached DataFrames

**File-based previous-year cache** (`backend/data/.cache/`):
- CSV files with 30-day TTL
- Previous-year P&L/BS data changes rarely, so this avoids repeated DB round-trips

### DataFrame → JSON Sanitization
- `_sanitize_value()` converts numpy/pandas types to JSON-safe Python types
- `np.integer` → `int`, `np.floating` → `round(float, 2)`, `np.nan` → `None`, `np.bool_` → `bool`
- `_df_to_records()` applies this to every cell before returning to the API

### NOTA_GROUPS — Config-Driven Report Rendering
- `backend/config/nota.py` defines `NOTA_GROUPS`: a tuple of `NotaGroup` entries
- Each `NotaEntry` specifies: label, render pattern, data domain (BS/PL), data keys
- `RenderPattern` enum controls how each note renders (BS detail, PL by CECO, PL by cuenta, sales, etc.)
- Both Excel sheet order AND PDF note numbering are driven by the same config
- Reordering `NOTA_GROUPS` changes both outputs simultaneously
- `numbered_groups()` helper auto-numbers notes and skips empty groups

### Month Column Ordering
- `MONTH_NAMES_LIST` (in `backend/config/calendar.py`) is the single source of calendar-ordered month names
- Use `reindex(columns=non_month_cols + MONTH_NAMES_LIST, fill_value=0)` to ensure all 12 month columns exist in order
- Never reconstruct via `list(MONTH_NAMES.values())` — import `MONTH_NAMES_LIST` instead

### Account Classification Rules
- `backend/services/accounting/rules.py` defines constants for account prefix matching
- `assign_partida_pl()` uses `np.select()` for vectorized classification (priority-ordered conditions)
- Cost-center first character determines cost vs. sales expense vs. admin expense
- BS classification maps account prefixes → statement line items, with per-account overrides
- Account prefix parsing uses `_cuenta_digits()` (dot-removal for numeric comparison) and `_cuenta_prefix(s, n)` (first n chars of dotted code) in `transforms.py`

### Accounting Logic — SACRED, DO NOT MODIFY

The accounting transformation pipeline is the core of this system. Its logic must NEVER be altered by UI changes, refactoring, or "improvements" unless explicitly requested for accounting correctness reasons.

**Protected modules** (changes require explicit accounting justification):
- `backend/services/accounting/rules.py` — Account classification constants, BS mappings, display order, reclassification rules
- `backend/services/accounting/transforms.py` — SALDO computation (P&L: CREDITO−DEBITO; BS: sign by account class), account filtering (prefix ≥ 619), partida assignment (np.select priority order)
- `backend/services/accounting/statements.py` — P&L row structure (subtotal formulas: UTILIDAD BRUTA, OPERATIVA, NETA), BS row structure (CORRIENTE/NO CORRIENTE split, reclassification, Resultados del Ejercicio injection), balance validation (ACTIVO = PASIVO + PATRIMONIO)
- `backend/services/accounting/aggregation.py` — Pivot logic (monthly sums, cumsum for BS), period aggregation, resultado financiero split (prefix "77" = ingresos)
- `backend/data/queries.py` — SQL query construction, account prefix filtering, date range logic, closing entry exclusion

**Sacred invariants** (must hold true at all times):
1. P&L SALDO = CREDITO_LOCAL − DEBITO_LOCAL (never reversed)
2. BS SALDO: Assets (1,2,3) = DEBITO − CREDITO; Liabilities/Equity (4,5) = CREDITO − DEBITO
3. BS accounts with negative cumulative balance are reclassified per BS_RECLASSIFICATION_RULES (sign flipped on section change)
4. Cross-section overrides (native section ≠ assigned section) flip sign automatically
5. `assign_partida_pl()` uses np.select — first matching condition wins; rule order is intentional
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
- **Path traversal defense**: Download endpoint uses `os.path.basename()` + `os.path.realpath()` to ensure resolved path stays within `output_dir`
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
  - Export state: isExporting, export errors
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
│           ├── TopBar (company selector, year selector, granularity toggle, period range toggle)
│           ├── Sidebar (view navigation, export buttons)
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

### Export/Download Pattern
- Frontend POSTs to `/api/export/{excel|pdf|all}` with company/year
- Backend generates file, returns `{ excel: "filename.xlsx", pdf: "filename.pdf" }`
- Frontend opens `GET /api/export/download/<filename>` in a new tab to trigger download

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
