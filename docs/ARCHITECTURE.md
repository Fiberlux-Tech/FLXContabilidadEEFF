# Architecture

## Monorepo Structure

```
FLXContabilidad/
├── backend/              # All Python: Flask API + services + data + config
│   ├── app.py            # Flask app factory, sys.path setup, CORS, blueprint registration
│   ├── auth.py           # SQLite-based session auth (login, logout, /me, rate limiting)
│   ├── routes.py         # API endpoints (data loading, drill-down)
│   ├── scripts/          # Operational CLIs (manage_users.py: create, list, delete, set-password, set-admin)
│   ├── gunicorn.conf.py  # Production WSGI server config
│   ├── logs/             # Access/error logs
│   ├── services/         # Python data pipeline
│   │   ├── data_service.py   # Single-fetch service with in-memory cache (3-hour TTL)
│   │   └── accounting/       # Transforms, aggregation, P&L/BS statement builders, rules
│   ├── config/           # Shared config (settings, calendar, fields, company, exceptions)
│   └── data/             # Data layer (db pool, SQL queries, fetcher)
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
Browser (http://10.100.50.4)
    │
    ▼
Nginx (:80)
    ├── Static files → frontend/dist/
    ├── /auth/*      → Gunicorn (127.0.0.1:5000) → Flask auth.py
    └── /api/*       → Gunicorn (127.0.0.1:5000) → Flask routes.py → services/
```

See [DEPLOYMENT.md](DEPLOYMENT.md) for the deploy workflow and on-box layout.

## API Endpoints

| Method | Endpoint                         | Description                              |
|--------|----------------------------------|------------------------------------------|
| GET    | /auth/me                         | Check session status                     |
| POST   | /auth/login                      | Authenticate user                        |
| POST   | /auth/logout                     | End session                              |
| GET    | /api/companies                   | Company list with metadata               |
| GET    | /api/health                      | Health check                             |
| GET    | /api/cache-stats                 | Cache hit/miss counters and entry counts |
| POST   | /api/data/load                   | Fetch + transform full P&L + BS report   |
| POST   | /api/data/load-pl                | Fetch P&L summary only (BS pre-fetched in background) |
| POST   | /api/data/load-bs                | Fetch BS summary + note tables (requires P&L loaded first) |
| POST   | /api/data/pl-section             | Fetch one P&L detail section on demand   |
| POST   | /api/data/detail                 | Drill-down into journal entries           |
| GET    | /api/headcount                   | Headcount map keyed by CECO              |
| GET    | /api/headcount/ym                | Headcount map keyed by `YYYYMM`          |
| GET    | /api/headcount/roster            | Employees for one (company, CECO, month) |
| POST   | /api/admin/headcount/upload      | Upload employee-roster CSV (admin)       |

The dashboard's "Export current view to Excel" button is implemented entirely in the frontend (SheetJS in the browser) and does not call any backend endpoint.

## Authentication
- **Storage**: SQLite file (`backend/users.db`)
- **Method**: Flask server-side sessions with secure cookies
- **No signup page** — users are created via CLI: `python backend/scripts/manage_users.py create`
- **Session flow**: Login → cookie set → all requests include cookie → /auth/me verifies
- **Rate limiting**: Failed logins are rate-limited per IP

## Data Flow

### Dashboard Load
```
POST /api/data/load { company: "FIBERLUX", year: 2026 }
    │
    ▼
data_service.load_report_data()
    ├── Check in-memory `result` cache (3-hour TTL) → return if fresh
    │
    ├── P&L summaries (Phase C): fetch_pnl_summary_only → pl_summary_from_view
    │       (~100 rows from VISTA_PNL_SUMARIO; total / ex_ic / only_ic variants)
    │
    ├── P&L detail sections (Phase F): one fetch from VISTA_PNL_PREAGG sliced into
    │       a (preagg, preagg_ex_ic, preagg_only_ic) triple → compute_pl_section
    │       across the SECTION_REGISTRY (ingresos, costo, gasto_venta, gasto_admin,
    │       otros_egresos, dya, resultado_financiero, diferencia_cambio, plus the
    │       analysis_* sections). No row-level df_stmt; no Python row aggregation.
    │
    ├── BS summary (Phase C): fetch_bs_summary_only → bs_summary_from_view
    │       (~360 rows from VISTA_BS_SUMARIO; Resultados-del-Ejercicio injection
    │       reads from the P&L summary above). BS note tables come from
    │       VISTA_BS_PREPARADO_CUMSUM + VISTA_BS_DETALLE_NIT_CUMSUM via
    │       load_bs_data — not from this entry point.
    │
    ├── Cache: result dict + cross-populate pl_result / bs_result / pl_df /
    │          pl_preagg_triple buckets so split-endpoint calls hit warm
    │
    └── Response: { pl_summary, pl_summary_ex_ic, pl_summary_only_ic, bs_summary,
                    ingresos_ordinarios, ingresos_proyectos, costo, gasto_venta,
                    gasto_admin, dya_costo, dya_gasto, otros_ingresos, otros_egresos,
                    resultado_financiero_ingresos, resultado_financiero_gastos,
                    diferencia_cambio_*, *_ex_ic / *_only_ic variants,
                    company, year, months }
```

The split endpoints (`/api/data/load-pl`, `/api/data/load-bs`, `/api/data/pl-section`) let the dashboard fetch P&L first and lazy-load BS + each detail section as the user navigates. P&L summary load also kicks off background prefetches: BS, prev-year P&L preagg (trailing 12M), and the most-clicked sections (ingresos / costo / gasto_admin). All prefetches are gated by a free-RAM check.

### Export Flow

Excel export of the currently-displayed view is fully client-side:
`useViewExport` in the dashboard reads the current report state from
`ReportContext`, builds sheet definitions in the browser, and hands them
to SheetJS to produce a `.xlsx` download. No `/api/export/*` endpoint
exists — the backend is a pure JSON API.

## Caching Strategy

In-memory LRU+TTL only — the disk-pickle layer and the cross-worker `fcntl` flock were deleted in SQL Views Phase C+1 (2026-05-29) once Phase F shrank the cached payloads to small SQL-view results.

`data_service.py` keeps six LRU+TTL buckets, each keyed by `(company, year)`, 3-hour TTL, default `max_entries=20`:

| Bucket | Holds |
|--------|-------|
| `result` | Full `load_report_data` response (P&L summary + BS summary + all detail sections) |
| `pl_result` | P&L summary-only response (`load_pl_data` fast path) |
| `bs_result` | BS summary + note-table response (`load_bs_data`) |
| `pl_df` | P&L summary DataFrame — kept around so `load_bs_data` can inject Resultados del Ejercicio |
| `pl_sections` | Per-section detail records produced by `load_pl_section`, keyed inside the bucket by `section[:kwargs]` |
| `pl_preagg_triple` | The `(preagg, preagg_ex_ic, preagg_only_ic)` triple sliced from one `VISTA_PNL_PREAGG` fetch — shared by every detail section |

Per-key writes are guarded by a `threading.Lock`; concurrent misses for the same `(company, year, kind)` coalesce on an in-process single-flight lock so only the first thread fires the SQL query. There is no cross-worker dedup — each Gunicorn worker has its own cache, and at 2 workers the worst case is each worker firing the same cheap SQL-view query once on a cold miss.

## Accounting Logic Boundary

The accounting transformation pipeline is **sacred** — it must not be modified by UI changes, refactoring, or coding improvements. Only intentional accounting corrections are allowed.

**Backend owns all accounting logic** — transforms, classification, subtotals, sign rules, reclassification, balance validation. See `docs/CODING_PATTERNS.md` section "Accounting Logic — SACRED, DO NOT MODIFY" for the full list of protected modules and invariants.

**Frontend is presentation-only** — it may sum pre-computed monthly values for quarterly display, merge rows for trailing 12M, format numbers, and paginate. It must never compute accounting subtotals, reclassify accounts, or override backend values.

## Infrastructure
- **Server**: Ubuntu Linux at 10.100.50.4 — single prod tier (server-side staging decommissioned 2026-05-29; pre-prod validation runs on a developer laptop clone against the same read-only SQL Server)
- **Process manager**: systemd (`flxcontabilidad.service`)
- **WSGI server**: Gunicorn (2 sync workers on `127.0.0.1:5000`; configurable via `GUNICORN_*` env vars in `backend/gunicorn.conf.py`)
- **Reverse proxy**: Nginx on `:80`
- **Frontend build**: Vite (static files in `frontend/dist/`)
- **Python**: 3.12 with venv at `venv/`
- **Node**: For frontend build only (not needed at runtime)
- **Deploy**: `./deploy.sh` in the prod working tree — see [DEPLOYMENT.md](DEPLOYMENT.md)
