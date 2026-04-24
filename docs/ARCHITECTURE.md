# Architecture

## Monorepo Structure

```
FLXContabilidad/
├── backend/              # All Python: Flask API + services + data + config
│   ├── app.py            # Flask app factory, sys.path setup, CORS, blueprint registration
│   ├── auth.py           # SQLite-based session auth (login, logout, /me, rate limiting)
│   ├── routes.py         # API endpoints (data loading, exports, downloads, drill-down)
│   ├── manage.py         # CLI for user management (create, list, delete, reset-password)
│   ├── gunicorn.conf.py  # Production WSGI server config
│   ├── output/           # Generated Excel/PDF files
│   ├── logs/             # Access/error logs
│   ├── services/         # Python data pipeline
│   │   ├── data_service.py   # Single-fetch service with in-memory cache (30-min TTL)
│   │   ├── pipeline.py       # Orchestrator: fetch → transform → export Excel/PDF
│   │   ├── accounting/       # Transforms, aggregation, P&L/BS statement builders, rules
│   │   ├── excel/            # Multi-sheet Excel generation (openpyxl)
│   │   └── pdf/              # PDF generation (fpdf2) — cover, tables, notes
│   ├── config/           # Shared config (settings, calendar, fields, company, nota, exceptions)
│   ├── data/             # Data layer (db pool, SQL queries, fetcher, disk cache)
│   └── models/           # Data model classes (PeriodContext, PnLReportData, PdfReportData)
├── frontend/             # React + Vite + Tailwind
│   ├── src/
│   │   ├── App.tsx       # Root component (auth check → login or dashboard)
│   │   ├── lib/api.ts    # Centralized HTTP client (cookies, error handling)
│   │   ├── config/       # Constants, API endpoints
│   │   ├── types/        # TypeScript interfaces
│   │   ├── contexts/     # AuthContext (user state) + ReportContext (data/export/display state)
│   │   ├── components/   # Shared components (ErrorBoundary)
│   │   └── features/
│   │       ├── auth/     # Login page + auth service
│   │       └── dashboard/  # DashboardShell, TopBar, Sidebar, MainContent,
│   │                       # FinancialTable, DetailTable, PLNoteView
│   └── dist/             # Production build (served by nginx)
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
| POST   | /api/export/excel                | Generate Excel report                    |
| POST   | /api/export/pdf                  | Generate PDF report                      |
| POST   | /api/export/all                  | Generate Excel + PDF                     |
| GET    | /api/export/download/\<filename> | Download a generated file                |

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
    │   └── Returns: raw, raw_current_full, raw_prev, raw_bs, raw_bs_prev
    │
    ├── Transforms: prepare_pnl → filter_for_statements → assign_partida_pl → pl_summary
    ├── BS: prepare_bs_stmt → bs_summary
    ├── Detail pivots: preaggregate → sales_details, proyectos_especiales,
    │   detail_by_ceco (costo, gasto_venta, gasto_admin, dya_costo, dya_gasto),
    │   detail_resultado_financiero (ingresos/gastos split)
    │
    ├── Cache: result dict + raw DataFrames + prepared BS + statement DataFrame
    │
    └── Response: { pl_summary, bs_summary, ingresos_ordinarios, ingresos_proyectos,
                    ingresos_intercompany, costo, gasto_venta, gasto_admin, dya_costo, dya_gasto,
                    resultado_financiero_ingresos, resultado_financiero_gastos,
                    company, year, months }
```

### Export Flow
```
POST /api/export/excel { company: "FIBERLUX", year: 2026 }
    │
    ▼
_run_export()
    ├── Attempt to reuse cached raw DataFrames from prior dashboard load
    │   (eliminates redundant SQL Server round-trips)
    │
    ├── pipeline.run_report() → build_excel_data → export_to_excel → .xlsx
    │                         → build_pdf_data  → export_to_pdf  → .pdf
    │
    └── Response: { excel: "filename.xlsx", pdf: "filename.pdf" }
        │
        ▼
    Frontend opens: GET /api/export/download/filename.xlsx → send_file()
```

## Caching Strategy

Three layers, each serving a different purpose:

| Layer | Location | TTL | Purpose |
|-------|----------|-----|---------|
| **In-memory** | `data_service.py` | 30 min | Fast dashboard reloads without DB queries |
| **Export reuse** | `data_service.py` (raw cache) | 30 min | Export skips DB if dashboard already loaded |
| **File-based** | `backend/data/.cache/` (CSV) | 30 days | Previous-year P&L/BS data (changes rarely) |

All in-memory caches are keyed by `(company, year)` and protected by `threading.Lock`.

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
