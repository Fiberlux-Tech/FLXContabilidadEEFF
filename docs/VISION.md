# Vision & Goals

## Project: FLXContabilidad

### What Is This?
A web-based dashboard that allows non-technical users to view and analyze financial reports (P&L and Balance Sheet) for the Fiberlux group of companies. Users see everything in the browser — monthly breakdowns, revenue details, drill-down into journal entries — and can export to Excel and/or PDF when needed.

This replaces a CLI-only Python tool (`python main.py --company FIBERLUX --year 2026 --month 1`) that required terminal access and generated files locally.

### Companies Served
- FIBERLINE PERU S.A.C. (RUC: 20601594791)
- FIBERLUX S.A.C. (RUC: 20557425889)
- FIBERLUX TECH S.A.C. (RUC: 20607403903)
- NEXTNET S.A.C. (RUC: 20546904106)

### Core Workflow
1. User logs in to `http://10.100.50.4`
2. Selects company and year from the top bar
3. Chooses granularity (monthly / quarterly) and period range (YTD / trailing 12 months)
4. Data auto-loads from SQL Server (debounced, with 30-min caching)
5. Views P&L and Balance Sheet summaries in the dashboard
6. Switches between views: P&L, Balance Sheet, Ingresos, Costo, Gastos (Venta/Admin), D&A, Resultado Financiero
7. Drills down into any cell to see underlying journal entries (account, NIT, cost center, date, amount)
8. Exports to Excel, PDF, or both when a downloadable report is needed

### Key Capabilities
- **View everything in-browser**: No need to generate files just to see the numbers. The dashboard shows P&L summaries, BS summaries, and revenue breakdowns directly.
- **Drill-down**: Click any cell in the Ingresos view to see the raw journal entries behind it, with filtering by account, NIT, cost center.
- **Export on demand**: Generate Excel (multi-sheet with notes) and/or PDF (cover + P&L + BS + notes) reports for sharing or archival.
- **Fast reloads**: In-memory caching (30-min TTL) means switching between views or re-exporting doesn't re-query SQL Server.

### Data Source
- SQL Server database via ODBC
- Single view: `REPORTES.VISTA_ANALISIS_CECOS`
- Key dimensions: CIA, CUENTA_CONTABLE, CENTRO_COSTO, NIT, FECHA
- Measures: DEBITO_LOCAL, CREDITO_LOCAL

### Non-Goals
- This is NOT a general-purpose accounting system
- This does NOT modify any data in SQL Server (read-only)
- No multi-tenant support — single deployment for all four companies
- No public internet access — internal network only (10.100.50.4)
- No email sending — reports are downloaded directly from the browser
