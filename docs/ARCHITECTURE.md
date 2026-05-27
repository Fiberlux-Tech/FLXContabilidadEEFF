# Architecture

## Monorepo Structure

```
FLXContabilidad/
├── backend/              # All Python: Flask API + services + data + config
│   ├── app.py            # Flask app factory, sys.path setup, CORS, blueprint registration
│   ├── auth.py           # SQLite-based session auth (login, logout, /me, rate limiting)
│   ├── routes.py         # API endpoints (data loading, drill-down)
│   ├── manage.py         # CLI for user management (create, list, delete, reset-password)
│   ├── gunicorn.conf.py  # Production WSGI server config
│   ├── logs/             # Access/error logs
│   ├── services/         # Python data pipeline
│   │   ├── data_service.py   # Single-fetch service with in-memory cache (30-min TTL)
│   │   └── accounting/       # Transforms, aggregation, P&L/BS statement builders, rules
│   ├── config/           # Shared config (settings, calendar, fields, company, exceptions)
│   └── data/             # Data layer (db pool, SQL queries, fetcher, disk cache)
├── frontend/             # React + Vite + Tailwind
│   ├── src/
│   │   ├── App.tsx       # Root component (auth check → login or dashboard)
│   │   ├── lib/api.ts    # Centralized HTTP client (cookies, error handling)
│   │   ├── config/       # Constants, API endpoints
│   │   ├── types/        # TypeScript interfaces
│   │   ├── contexts/     # AuthContext (user state) + ReportContext (data/display state)
│   │   ├── components/   # Shared components (ErrorBoundary)
│   │   └── features/
│   │       ├── auth/     # Login page + auth service
│   │       └── dashboard/  # DashboardShell, TopBar, Sidebar, MainContent,
│   │                       # FinancialTable, DetailTable, PLNoteView
│   └── dist/             # Production build (served by nginx)
├── sql/                  # DDL for views that push transforms into SQL Server
│                         # (VISTA_PNL_PREPARADO, VISTA_BS_PREPARADO, parity checks)
│                         # See sql/README.md for topology + deployment order
├── .env                  # Shared defaults
├── .env.development      # Dev-specific overrides
├── .env.production       # Production overrides
├── requirements.txt      # Python dependencies
└── docs/                 # This documentation
```

## Request Flow

```
Browser (http://10.100.50.4           for prod,
         http://10.100.50.4:8081      for staging)
    │
    ▼
Nginx (:80 prod, :8081 staging — one machine, split by port)
    ├── Static files → frontend/dist/ in the matching working tree
    ├── /auth/*      → Gunicorn (prod :5000 / staging :5001) → Flask auth.py
    └── /api/*       → Gunicorn (prod :5000 / staging :5001) → Flask routes.py → services/
```

See [DEPLOYMENT.md](DEPLOYMENT.md) for full staging + prod topology.

## API Endpoints

| Method | Endpoint                         | Description                              |
|--------|----------------------------------|------------------------------------------|
| GET    | /auth/me                         | Check session status                     |
| POST   | /auth/login                      | Authenticate user                        |
| POST   | /auth/logout                     | End session                              |
| GET    | /api/companies                   | Company list with metadata               |
| GET    | /api/health                      | Health check                             |
| GET    | /api/cache-stats                 | Cache hit/miss counters and entry counts |
| POST   | /api/data/load                   | Fetch + transform report data            |
| POST   | /api/data/load-pl                | Fetch P&L only (BS pre-fetched in background) |
| POST   | /api/data/load-bs                | Fetch BS only (requires P&L loaded first) |
| POST   | /api/data/detail                 | Drill-down into journal entries           |

The dashboard's "Export current view to Excel" button is implemented entirely in the frontend (SheetJS in the browser) and does not call any backend endpoint.

## Authentication
- **Storage**: SQLite file (`backend/users.db`)
- **Method**: Flask server-side sessions with secure cookies
- **No signup page** — users are created via CLI: `python manage.py create-user`
- **Session flow**: Login → cookie set → all requests include cookie → /auth/me verifies
- **Rate limiting**: Failed logins are rate-limited per IP

## Data Flow

### Dashboard Load
```
POST /api/data/load { company: "FIBERLUX", year: 2026 }
    │
    ▼
data_service.load_report_data()
    ├── Check in-memory cache (30-min TTL) → return if fresh
    │
    ├── fetch_all_data() → concurrent SQL Server queries (ThreadPoolExecutor)
    │   └── Returns: (raw_current_full, raw_bs)
    │
    ├── Summary (Phase C): fetch_pnl_summary_only + fetch_bs_summary_only →
    │       pl_summary_from_view / bs_summary_from_view  (~100 + ~360 rows from
    │       VISTA_PNL_SUMARIO / VISTA_BS_SUMARIO; no row-level aggregation in Python)
    │
    ├── Detail prep: prepare_pnl_from_view (dtype adapter; classification already done by SQL view) →
    │       preaggregate → sales_details, proyectos_especiales,
    │       detail_by_ceco (costo, gasto_venta, gasto_admin, dya_costo, dya_gasto),
    │       detail_resultado_financiero (ingresos/gastos split).  Row-level df_stmt
    │       cached for drill-down (until Phase D ships paginated SQL drill-down).
    │
    ├── Cache: result dict + row-level df_stmt + prepared BS + section preaggs
    │
    └── Response: { pl_summary, bs_summary, ingresos_ordinarios, ingresos_proyectos,
                    ingresos_intercompany, costo, gasto_venta, gasto_admin, dya_costo, dya_gasto,
                    resultado_financiero_ingresos, resultado_financiero_gastos,
                    company, year, months }
```

### Export Flow

Excel export of the currently-displayed view is fully client-side:
`useViewExport` in the dashboard reads the current report state from
`ReportContext`, builds sheet definitions in the browser, and hands them
to SheetJS to produce a `.xlsx` download. No `/api/export/*` endpoint
exists — the backend is a pure JSON API.

## Caching Strategy

Two layers, each serving a different purpose:

| Layer | Location | TTL | Purpose |
|-------|----------|-----|---------|
| **In-memory** | `data_service.py` (LRU+TTL) | 30 min | Fast dashboard reloads without DB queries |
| **File-based** | `backend/.stmt_cache/` (pickle) | on-demand fill, no TTL | Cold-start path for prepared P&L/BS DataFrames |

All in-memory caches are keyed by `(company, year)` and protected by `threading.Lock`; cross-worker concurrent fills are deduped by an `fcntl` flock (`/tmp/flx_inflight_*.lock`). The disk pickle layer is slated for removal in SQL views Phase C+1 (see [SQL_VIEWS_ROADMAP.md](SQL_VIEWS_ROADMAP.md)) once Phase C shrinks the cached payload to ~10 KB.

## Accounting Logic Boundary

The accounting transformation pipeline is **sacred** — it must not be modified by UI changes, refactoring, or coding improvements. Only intentional accounting corrections are allowed.

**Backend owns all accounting logic** — transforms, classification, subtotals, sign rules, reclassification, balance validation. See `docs/CODING_PATTERNS.md` section "Accounting Logic — SACRED, DO NOT MODIFY" for the full list of protected modules and invariants.

**Frontend is presentation-only** — it may sum pre-computed monthly values for quarterly display, merge rows for trailing 12M, format numbers, and paginate. It must never compute accounting subtotals, reclassify accounts, or override backend values.

## Infrastructure
- **Server**: Ubuntu Linux at 10.100.50.4 — hosts both prod and staging
- **Process manager**: systemd (`flxcontabilidad.service` for prod, `flxcontabilidad-staging.service` for staging)
- **WSGI server**: Gunicorn (3 sync workers; prod on :5000, staging on :5001)
- **Reverse proxy**: Nginx (prod on :80, staging on :8081)
- **Frontend build**: Vite (static files in `frontend/dist/`)
- **Python**: 3.12 with venv (separate venv per working tree)
- **Node**: For frontend build only (not needed at runtime)
- **Deploy**: `./deploy.sh` in each working tree — see [DEPLOYMENT.md](DEPLOYMENT.md)
