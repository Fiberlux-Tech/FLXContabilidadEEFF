# SQL Views Roadmap — push transforms into the database

> **Status**: Phase A in progress. P&L parity proven on 2024–2026 against the original (filter-based) view; redesigned (enrichment) view DDL committed in [`02228d9`](https://github.com/Fiberlux-Tech/FLXContabilidadEEFF/commit/02228d9), awaiting DBA redeploy.
> **Owner**: Backend team. DDL deploys require DBA (current `STERNERO` login is SELECT-only on the new views).
> **Last updated**: 2026-05-22.
> **Related**: [SCALING_ROADMAP.md](SCALING_ROADMAP.md) (memory budget — these views reduce per-request CPU but don't change the cache-warmth strategy), [SCHEDULED_REFRESH.md](SCHEDULED_REFRESH.md) (the hourly refresh path is what consumes these views).

## Why this document exists

The finance team gained the ability to add views to the `ROP` SQL Server (alongside `REPORTES.VISTA_ANALISIS_CECOS`) on 2026-05-22. That unlocks a structural change: **classification and shape transforms that today live in `backend/services/accounting/transforms.py` can move into the database**, so Flask receives data already enriched with `SALDO`, `PARTIDA_PL`, `IS_INTERCOMPANY`, etc.

Two wins:

1. **Latency**: aggregated dashboard queries become 3.4–7.9× faster (probe results below). Raw fetches 1.6–1.7× faster.
2. **One source of truth**: today the classification rules exist in Python and **also** as embedded knowledge in any SQL written by the finance team for Excel-via-ODBC. Pushing the rules into a view collapses those into one place — the view definition.

This is independent of the scaling/refresh work in the other docs. The cache architecture stays the same; the *contents* of what's cached become smaller and cheaper to compute.

## Constraints discovered during phase A

- **DDL deployment requires DBA.** STERNERO has `SELECT WITH GRANT OPTION` on the source views and `SELECT` on the new views, but cannot `CREATE VIEW` in any schema other than its own. Every DDL change ships as a `.sql` file in `sql/` and we ask the DBA to run it.
- **Per-CIA topology required for predicate pushdown.** `VISTA_ANALISIS_CECOS` is a `UNION ALL` of four per-company views, so any new umbrella view in `REPORTES` must follow the same shape to let the optimizer prune to one company when `CIA = ?` is filtered. We deploy 4 per-CIA views + a `REPORTES` umbrella for each statement.
- **Trailing-space padding in source.** ~9% of rows have padded `CUENTA_CONTABLE` / `CENTRO_COSTO`. Source views don't `RTRIM`. New views must wrap text cols in `RTRIM()` once at the bottom, otherwise `LEFT()` / `LIKE` slices misbehave for those rows.
- **The view enriches, it does not filter.** A row that doesn't belong to the statement (e.g. inventory account `60.x` or the synthetic `79.1.1.1.01`) is still returned by the view, carrying `IS_STATEMENT_ELIGIBLE = 0`. Callers add `WHERE IS_STATEMENT_ELIGIBLE = 1` for the statement; the Excel raw-pivot path uses the unfiltered set. **This is what makes one view serve both surfaces.**
- **Parity must precede deletion.** `sql/parity_check.py` compares per-`(CIA, MES, PARTIDA)` `SUM(SALDO)` from the view against the current Python pipeline. No Python code gets deleted until that script prints `PARITY OK ✓` for every year that has data.

## Roadmap

### Phase A — P&L migration  (in progress)

**Goal.** P&L classification (`prepare_pnl` → `filter_for_statements` → `assign_partida_pl`) moves from Python to SQL. Three Python functions and ~16 rule constants get deleted from the repo. The view returns enriched rows; eligibility is exposed via the `IS_STATEMENT_ELIGIBLE` flag so the same view feeds the website *and* the Excel raw pivots.

**What is shipped today (2026-05-22).**

- `sql/VISTA_PNL_PREPARADO.sql` — DDL for 4 per-CIA views + REPORTES umbrella. Original (filter-based) version live in DB since 2026-05-22 15:31. **Redesigned (enrichment + `IS_STATEMENT_ELIGIBLE`) version committed but not yet deployed.**
- `sql/parity_check.py` — regression harness. Confirmed `PARITY OK` for 2024, 2025, 2026 against the original view (763 `(CIA × MES × PARTIDA_PL)` rows, zero mismatches).
- `sql/PARITY_CHECKS.sql` — SQL-only sanity checks (POR CLASIFICAR coverage, section consistency, row counts).
- `sql/README.md` — deployment / parity workflow.

**Performance evidence (2025 full-year, best of 3 runs):**

| Surface                 | Old (Python)    | New (view)    | Speedup |
|-------------------------|----------------:|--------------:|--------:|
| FIBERLINE raw fetch     | 18.6 s          | 11.0 s        | 1.69×   |
| FIBERLINE aggregated    | 19.4 s          | 3.5 s         | 5.57×   |
| FIBERTECH aggregated    | 10.4 s          | 3.1 s         | 3.40×   |
| FIBERLUX aggregated     | 1.4 s           | 0.2 s         | 6.94×   |
| NEXTNET aggregated      | 1.1 s           | 0.14 s        | 7.95×   |

The aggregated row is the one the dashboard's `pl_summary` actually needs. The "raw fetch" win matters for code paths that still need row-level data (Excel raw pivots, detail tables).

**Step 1 (blocked on DBA).** Redeploy `sql/VISTA_PNL_PREPARADO.sql` so the live view exposes `IS_STATEMENT_ELIGIBLE` and no longer pre-filters `prefix-3 >= 619` / `<> '79.1.1.1.01'`. Idempotent (`CREATE OR ALTER VIEW`), no permission changes needed.

**Step 2 (this team).** Re-run `venv/bin/python sql/parity_check.py --year 2024` / `2025` / `2026`. Expect `PARITY OK ✓`. If anything fails, the deletion in step 4 doesn't happen.

**Step 3 (this team).** Wire callers to the view:
  - `backend/data/queries.py:79-85` — point `fetch_pnl_data` at `REPORTES.VISTA_PNL_PREPARADO`, drop the `LIKE '6/7/8%'` / `FUENTE NOT LIKE 'CIERRE%'` filters (the view does both).
  - `backend/services/data_service.py:707, 785, 887-889` — pl_summary path. Push aggregation into SQL where applicable (the 8× win); detail tables keep fetching row-level prepared data and group in pandas.
  - `backend/services/excel/builder.py:104-114` — switch from `prepare_pnl(raw) → filter_for_statements(df) → assign_partida_pl(df_stmt)` to a single fetch. Raw pivots use the full view; the statement pivots add `WHERE IS_STATEMENT_ELIGIBLE = 1`.
  - `backend/services/pdf/builder.py:34, 37` — drop the `prepare_stmt(raw)` calls; the fetched data is already prepared.

**Step 4 (this team).** Delete:
  - `prepare_pnl`, `filter_for_statements`, `assign_partida_pl`, `prepare_stmt` from `backend/services/accounting/transforms.py`.
  - Unused rule constants from `backend/services/accounting/rules.py`: `PROVISION_INCOBRABLE_CUENTAS`, `DYA_GASTO_PREFIXES`, `PARTICIPACION_TRABAJADORES_CUENTA`, `DIFERENCIA_CAMBIO_PREFIXES`, `RESULTADO_FINANCIERO_PREFIXES`, `INGRESOS_ORDINARIOS_PREFIX`, `INGRESOS_INTERCOMPANY_CUENTAS`, `INTERCOMPANY_CECO_PATTERN`, `INGRESOS_PROYECTOS_CUENTA`, `OTROS_INGRESOS_PREFIXES`, `IMPUESTO_RENTA_FIRST_CHAR`, `EXCLUDED_CUENTA`, `CECO_PREFIX_*` (6 constants).
  - `PNL_ACCOUNT_PREFIXES` — used in queries.py:85 today; after step 3 the view handles the prefix filter, so this can go too.
  - Keep: `PL_SUBTOTAL_LABELS`, `DETAIL_CATEGORIES`, `INGRESO_FINANCIERO_PREFIX`. These are display / aggregation helpers, not classification rules.

**Success criteria.**
- `sql/parity_check.py --year 2024 --year 2025 --year 2026` prints `PARITY OK ✓` for all 4 companies on the live wire-up before step 4 lands.
- Dashboard `/api/data/load` end-to-end latency drops at least 3× on FIBERLINE.
- Excel export still includes the `by_cuenta` / `by_ceco` / `by_ceco_cuenta` raw sheets with the same row counts as today (inventory `60.x` accounts still present).
- `git grep prepare_pnl filter_for_statements assign_partida_pl PROVISION_INCOBRABLE_CUENTAS` returns zero hits in `backend/`.

### Phase B — Balance Sheet migration

**Goal.** Same shape as Phase A, applied to the BS pipeline: `prepare_bs` + `assign_partida_bs` move into `VISTA_BS_PREPARADO`. View returns `SALDO` (sign-aware per asset/liability), `MES`, `PARTIDA_BS`, `SECCION_BS`, and an eligibility flag if needed.

**What is shipped today.**
- `sql/VISTA_BS_PREPARADO.sql` — DDL committed but **not deployed yet**. The BS half of `parity_check.py` errors on the missing view (caught in [sql/parity_check.py output, 2026-05-22]).

**Open question / DBA decision.** Before redeploying BS, decide whether the same enrichment-not-filtering pattern applies. Current draft excludes only `FUENTE LIKE 'CIERRE%'` and filters to class 1-5 — there's no `>=619`-style scope rule, so the view is naturally permissive already. Likely no `IS_STATEMENT_ELIGIBLE` needed for BS.

**Out of scope for Phase B** (deferred to Phase C):
- Cumulative `SUM` across months (`statements.py bs_summary` cumsum).
- Reclassification rules: BS accounts that move sections when end-of-period balance is negative (`BS_RECLASSIFICATION_RULES`).
- `UTILIDAD NETA` injection from P&L into BS PATRIMONIO.
- `CORRIENTE` / `NO CORRIENTE` sub-section split.

Each of these is order-sensitive against the cumsum and likely needs a stored function or a Python passthrough. Worth doing in pieces, not as one mega-view.

**Steps.**
1. **DBA**: deploy `sql/VISTA_BS_PREPARADO.sql`.
2. Re-run `sql/parity_check.py` end-to-end (it already has the BS path wired in). Expect `PARITY OK ✓` for BS totals.
3. Wire `fetch_bs_data` and `prepare_bs_stmt` callers to the view.
4. Delete `prepare_bs`, `assign_partida_bs`, BS-related constants (`BS_CLASSIFICATION`, `BS_CLASSIFICATION_OVERRIDES`, `BS_NATIVE_SECTION_MAP`, etc. — but **keep** `BS_PARTIDA_ORDER`, `BS_GROUP_TABLES`, `BS_SECTION_ORDER`, `BS_PARTIDA_LABELS`, `BS_ACTIVO_NO_CORRIENTE`, `BS_PASIVO_NO_CORRIENTE`; those are display ordering not classification).

### Phase C — pre-aggregated summary views  (only if profiling demands)

**Goal.** Push the `pl_summary` / `bs_summary` `GROUP BY` itself into SQL, so the dashboard fetches the summary table directly (~100 rows) instead of fetching row-level prepared data and grouping in pandas.

**Why "only if needed".** Phase A already buys 3-8× on aggregated fetches (the SQL `GROUP BY ... SUM(SALDO)` form was benchmarked above). If post-A latency is comfortable, Phase C is busywork. If a percentile sticks above target after A, this is where to look.

**Candidate views.**
- `REPORTES.VISTA_PNL_SUMARIO` — `GROUP BY CIA, MES, PARTIDA_PL` with `IS_INTERCOMPANY` filter variants (or three columns: total, ex_ic, only_ic).
- `REPORTES.VISTA_BS_SUMARIO_CUMSUM` — `GROUP BY CIA, PARTIDA_BS, SECCION_BS, MES` with `SUM(SUM(SALDO)) OVER (PARTITION BY … ORDER BY MES)` to do cumsum inside the view. Tricky because reclassification rules depend on the cumulative balance — see Phase B "out of scope" above.

**Decision point.** Don't start C until A has been in prod for at least 2 weeks and we have real p50/p95 numbers from `/api/cache-stats`.

### Phase D — detail-table push-downs  (probably not worth it)

**Goal.** Make `detail_by_ceco`, `detail_by_cuenta`, `detail_ceco_by_cuenta`, etc. into SQL views that the user can pull directly.

**Why probably not.** These run on already-cached `df_stmt` in memory; pandas grouping on prepared data is fast (sub-100 ms). The benefit would be removing the in-memory pivot cache (`preagg`) — small RAM win, not a latency win. Revisit only if the SCALING_ROADMAP memory budget gets tighter.

## Drift mitigation

Once Phase A's deletion commit lands, there is no Python fallback. If `VISTA_PNL_PREPARADO` drifts from the rules the team intended, the website silently shows wrong numbers.

**Mitigation:** `sql/parity_check.py` is preserved in the repo specifically as a regression harness. The Phase A deletion commit must be paired with a scheduled job that runs it weekly against current-year data; an `EXIT 1` on mismatch pages someone (notification target TBD).

**Not mitigated by:**
- Feature flag — we explicitly chose not to keep dual code paths. The Python pipeline doesn't exist after step 4.
- Unit tests in CI — we don't have CI on the SQL side, and unit-testing the CASE rules against fake data wouldn't catch source-data shape changes.

**What to do if parity fails post-deletion:**
1. Re-run `parity_check.py` locally; identify the divergent `(CIA, MES, PARTIDA_PL)` row.
2. Inspect the underlying `VISTA_ANALISIS_CECOS` rows for that partida. Most likely cause: a new account code added in the ERP that the view's CASE doesn't recognize. It will appear in the gaps endpoint (Phase A follow-up) as `POR CLASIFICAR`.
3. Either extend the view's CASE (DBA round-trip) or extend the source-view filter — depending on whether the new account is legitimately P&L or not.

## Classification-gaps surfacing  (follow-up, not in Phase A)

Today 412 rows land in `PARTIDA_PL = 'POR CLASIFICAR'` and ~5,000 BS rows in `POR DEFINIR …`. Net SALDO impact: ~0 PEN. They're visible on the dashboard as a "POR CLASIFICAR" line when non-zero, but easy to overlook. We considered two surfacing strategies:

- **SQL view** (`VISTA_CLASIFICACION_GAPS`) — written then [reverted in `547a793`](https://github.com/Fiberlux-Tech/FLXContabilidadEEFF/commit/547a793). The DDL was never deployed; the file is gone.
- **Python endpoint** (`/api/diagnostics/classification-gaps`) — preferred. Reuses the already-cached prepared DataFrame; one pandas filter, no extra DB roundtrip.

Will ship as a separate PR after Phase A's deletion lands.

## What's NOT in this roadmap

- Anything related to memory / cache sizing — see [SCALING_ROADMAP.md](SCALING_ROADMAP.md).
- Anything related to refresh scheduling — see [SCHEDULED_REFRESH.md](SCHEDULED_REFRESH.md).
- Stored procedures (we deliberately stick to views; no procedural SQL).
- Indexed / materialized views (would help cumsum-heavy Phase C; out of scope until then).
- Source-view (`VISTA_ANALISIS_CECOS`) changes. Those would need ERP-team coordination and are out of scope for this team.
