# SQL Views Roadmap — push transforms into the database

> **Status**: This is the **active capacity plan** as of 2026-05-28. **Phases A, B, C, D, and E are shipped.** Summaries read from `VISTA_PNL_SUMARIO` / `VISTA_BS_SUMARIO`; journal-entry drill-down reads from `VISTA_*_PREPARADO` via paginated SQL (Phase D). **The memory ceiling is NOT yet relieved** — see the 2026-05-28 finding below. Next up: **Phase F** (migrate P&L section detail + BS note tables off the row-level caches), which is the prerequisite that finally lets **Phase C+1** delete those caches and reclaim RAM.
> **Owner**: Backend team. DDL deploys require DBA (current `STERNERO` login is SELECT-only on the new views).
> **Last updated**: 2026-05-28.
>
> **⚠️ 2026-05-28 finding — the memory win has NOT landed yet.** A staging-vs-prod benchmark found prod at **98% RAM (0.1 GB free), swap-thrashing**: identical row-level fetches ranged 0.4 s → 285 s depending on whether the working set was resident or swapped out, and "warm" cache hits took 65 s because the cached DataFrame had been swapped to disk. Root cause: **Phases C and D shrank the *summary* and *drill-down* payloads, but every `load_pl_data` / `load_bs_data` still builds and caches the full ~400 MB row-level DataFrame** (`_caches["df"]` / `pl_stmt` / `pl_preagg` / `pl_preagg_ex_ic` / `pl_preagg_only_ic` / `bs`). Those caches survive because **`compute_pl_section` (P&L section detail tables) and the BS note tables (`bs_detail_by_cuenta`, `bs_top20_by_nit`) still read them.** Until those two consumers move to SQL (Phase F), the caches can't be deleted and the box stays memory-bound. This corrects the earlier Phase C claim that "the worker holds ~10 KB after Phase C" — true for the summary, false for resident memory.
> **Supersedes**: The Python-side Phase 2 (monthly fact pickles) plan that previously lived in [SCALING_ROADMAP.md](SCALING_ROADMAP.md) and `docs/FACT_TABLE.md` (deleted 2026-05-22). The SQL views path delivers the same aggregated artifact in the database engine, shared across all workers, with no per-worker pickle-load tax.
> **Related**: [SCALING_ROADMAP.md](SCALING_ROADMAP.md) (memory budget — Phase C of this doc is where the budget gets structurally easier).

## Why this document exists

The finance team gained the ability to add views to the `ROP` SQL Server (alongside `REPORTES.VISTA_ANALISIS_CECOS`) on 2026-05-22. That unlocks a structural change: **classification and aggregation that today live in `backend/services/accounting/transforms.py` and `aggregation.py` can move into the database**, so Flask receives data already enriched (Phase A/B) or already aggregated (Phase C).

Three wins:

1. **Latency**: aggregated dashboard queries become 3.4–7.9× faster after Phase A (probe results below). Raw fetches 1.6–1.7× faster. Phase C compounds on top.
2. **Concurrent-load headroom on the 5.8 GB box.** Phase C is the move that fixes the scaling problem at its source. Today each worker pulls 8.4M rows and groups them in pandas to produce ~100 summary rows; under concurrent load that pandas state is what pushes the box toward OOM. After Phase C, the view returns the ~100 rows directly and the worker holds ~10 KB instead of ~400 MB per cached `(company, year)`. **This is what unblocks scaling without buying more RAM.**
3. **One source of truth**: today the classification rules exist in Python and **also** as embedded knowledge in any SQL written by the finance team for Excel-via-ODBC. Pushing the rules into a view collapses those into one place — the view definition.

The cache architecture is now back to on-demand fill plus the in-memory LRU + disk pickle layers that existed before the scheduler. The scheduler is gone (see Phase A.5 below); after Phase A the per-request fetch is fast enough that pre-warming is unnecessary, and after Phase C the cached payload is small enough that cross-worker duplication stops mattering.

## Constraints discovered during phase A

- **DDL deployment requires DBA.** STERNERO has `SELECT WITH GRANT OPTION` on the source views and `SELECT` on the new views, but cannot `CREATE VIEW` in any schema other than its own. Every DDL change ships as a `.sql` file in `sql/` and we ask the DBA to run it.
- **Per-CIA topology required for predicate pushdown.** `VISTA_ANALISIS_CECOS` is a `UNION ALL` of four per-company views, so any new umbrella view in `REPORTES` must follow the same shape to let the optimizer prune to one company when `CIA = ?` is filtered. We deploy 4 per-CIA views + a `REPORTES` umbrella for each statement.
- **Trailing-space padding in source.** ~9% of rows have padded `CUENTA_CONTABLE` / `CENTRO_COSTO`. Source views don't `RTRIM`. New views must wrap text cols in `RTRIM()` once at the bottom, otherwise `LEFT()` / `LIKE` slices misbehave for those rows.
- **The view enriches, it does not filter.** A row that doesn't belong to the statement (e.g. inventory account `60.x` or the synthetic `79.1.1.1.01`) is still returned by the view, carrying `IS_STATEMENT_ELIGIBLE = 0`. Callers add `WHERE IS_STATEMENT_ELIGIBLE = 1` for the statement. Today the dashboard is the only caller, and it always passes `eligible_only=True`. The unfiltered set survives in the view for any future ad-hoc consumer (finance team's Excel-via-ODBC queries, the drill-down endpoint, etc.) — the cost is zero so we keep the optionality. *(Pre-2026-05-26 the server-side Excel export was a second caller that needed the unfiltered set; that pipeline has been deleted.)*
- **Parity must precede deletion.** Phase A's `sql/parity_check.py` compared per-`(CIA, MES, PARTIDA)` `SUM(SALDO)` from the view against the Python pipeline, and gated Step 4 on `PARITY OK ✓` for every year. That harness was deleted alongside Step 4 (the Python pipeline it compared against is gone). For Phases B / C, validation is one-shot — `sql/PARITY_CHECKS.sql` plus an ad-hoc Python diff script (not committed) that verifies to-the-centavo equivalence before the deletion commit lands.

## Roadmap

### Phase A — P&L migration  (shipped 2026-05-24)

**Goal.** P&L classification (`prepare_pnl` → `filter_for_statements` → `assign_partida_pl`) moves from Python to SQL. Python functions and rule constants get deleted from the repo. The view returns enriched rows; eligibility is exposed via the `IS_STATEMENT_ELIGIBLE` flag so the same view feeds the website *and* the Excel raw pivots.

**What is shipped.**

- `sql/VISTA_PNL_PREPARADO.sql` — DDL for 4 per-CIA views + REPORTES umbrella, with `IS_STATEMENT_ELIGIBLE` enrichment, live in DB.
- `backend/data/queries.py:fetch_pnl_data` reads from the view with an `eligible_only` flag (statement path filters to `IS_STATEMENT_ELIGIBLE = 1`; Excel raw-pivot path passes `eligible_only=False`).
- Dashboard ([data_service.py](../backend/services/data_service.py)) calls `prepare_pnl_from_view` — a thin dtype adapter — instead of the old classification pipeline. (Historical note: the Excel and PDF export pipelines were the other two callers; both were deleted when server-side multi-tab export was removed.)
- `prepare_pnl`, `filter_for_statements`, `assign_partida_pl`, `prepare_stmt`, the `_cuenta_digits` helper, and 19 PNL rule constants are **deleted** from `backend/services/accounting/`.
- `sql/parity_check.py` is **deleted**. The view is now the single source of truth; see "Drift mitigation" below for what replaces the harness.
- `sql/PARITY_CHECKS.sql` — SQL-only sanity checks (POR CLASIFICAR coverage, section consistency, row counts) — retained; run after any view DDL change.

**Performance evidence (2025 full-year, best of 3 runs):**

| Surface                 | Old (Python)    | New (view)    | Speedup |
|-------------------------|----------------:|--------------:|--------:|
| FIBERLINE raw fetch     | 18.6 s          | 11.0 s        | 1.69×   |
| FIBERLINE aggregated    | 19.4 s          | 3.5 s         | 5.57×   |
| FIBERTECH aggregated    | 10.4 s          | 3.1 s         | 3.40×   |
| FIBERLUX aggregated     | 1.4 s           | 0.2 s         | 6.94×   |
| NEXTNET aggregated      | 1.1 s           | 0.14 s        | 7.95×   |

The aggregated row is the one the dashboard's `pl_summary` actually needs. The "raw fetch" win matters for code paths that still need row-level data (Excel raw pivots, detail tables).

**Success criteria — met.**
- Dashboard `/api/data/load` end-to-end latency dropped substantially on FIBERLINE (per Phase A probe table above — 5.57× on the aggregated path).
- Excel export still includes the `by_cuenta` / `by_ceco` / `by_ceco_cuenta` raw sheets with inventory `60.x` accounts present (`eligible_only=False` returns the unfiltered set).
- `git grep prepare_pnl filter_for_statements assign_partida_pl PROVISION_INCOBRABLE_CUENTAS` returns zero hits in `backend/`.

### Phase A.5 — Scheduler deleted  (shipped 2026-05-22)

**Outcome.** The hourly cache refresh and its supporting CLI were deleted entirely: `backend/services/refresh_scheduler.py`, `backend/scripts/refresh_cache.py`, `docs/SCHEDULED_REFRESH.md`, and the `_start_refresh()` call in `backend/app.py`. We considered an env-gate intermediate step but chose outright deletion to avoid carrying dead code.

**Why this was the wrong design.** The scheduler was a 350+ line Python-side workaround for an expensive SQL query. It pre-fetched 8.4M rows × 8 cells, pickled 700+ MB to disk, and hoped 3 separate worker processes would deserialize fast enough. In prod the evidence (2026-05-22 logs) showed it was *worse than nothing* for FIBERLINE:

- 14 hourly cycles started in one day; only 3 completed. FIBERLINE 2025 + 2026 takes ~5 min combined and the cycle straddled the next hourly fire, which called `invalidate_cache` again before the previous refresh finished.
- Workers restarted 7 times in 2 hours (gunicorn `max_requests` recycle or cgroup pressure). Every restart killed the in-flight scheduler thread.
- FIBERLINE's disk pickle was stale by ~5 hours despite the scheduler claiming to refresh it hourly. Users hitting FIBERLINE between failed cycles paid the **full cold-cache cost (30–60 s)** because the pickle was invalidated by a cycle that never repopulated.
- Documented "known limitation": the scheduler only warmed 1 of 3 workers anyway; other workers always paid the 5–15 s pickle-load tax. The premise that the scheduler eliminated per-request DB queries was only ever half-true.

The expensive query was expensive because Python was doing classification + aggregation that the SQL engine could do in <1s. The right answer is to make the query cheap, not to hide it behind a scheduler. Phase A makes classification cheap (this is shipped); Phase C makes aggregation cheap. After both land, on-demand cache fill is sub-second per request — no pre-warming necessary.

**User-visible effect.**
- First click per `(company, year)` per worker: ~6 s (the new view-based fetch is much faster than the old ~30–60 s cold fetch — Phase A's win).
- Subsequent clicks: sub-second from cache (unchanged).
- No more mid-day invalidate-then-fail clobbers.
- Switching companies: still slow on cold workers until Phase C lands.

**What's left.** Stale `/tmp/flx_refresh.lock` on prod + staging hosts and a docs touch-up in `ARCHITECTURE.md`. Both folded into Phase C cleanup. (Earlier note about "delete force_refresh ignore plumbing" turned out to be wrong — `force_refresh` is real user-facing functionality, not scheduler leftover; nothing to delete.)

### Phase B — Balance Sheet migration  (shipped 2026-05-25)

**Goal.** Same shape as Phase A, applied to the BS pipeline: `prepare_bs` + `assign_partida_bs` move into `VISTA_BS_PREPARADO`. View returns `SALDO` (sign-aware per asset/liability), `MES`, `PARTIDA_BS`, `SECCION_BS`. BS is naturally permissive (filters to class 1-5 and excludes `FUENTE LIKE 'CIERRE%'`); no `IS_STATEMENT_ELIGIBLE` analog needed.

**What is shipped.**
- `sql/VISTA_BS_PREPARADO.sql` — DDL for 4 per-CIA views + REPORTES umbrella, deployed to prod 2026-05-22 (DBA pre-deployed before Python wiring landed).
- `backend/data/queries.py:fetch_bs_data` reads from the view; `_fetch_data` shared helper deleted along with it (Phase A had already left it with one caller).
- `backend/services/accounting/transforms.py` gained `prepare_bs_from_view` — a thin dtype adapter mirroring `prepare_pnl_from_view`. The old `prepare_bs` / `assign_partida_bs` / `prepare_bs_stmt` are **deleted**.
- `backend/services/accounting/rules.py`: deleted `BS_ACCOUNT_PREFIXES`, `BS_CLASSIFICATION`, `BS_CLASSIFICATION_OVERRIDES`. Kept `BS_PARTIDA_ORDER`, `BS_RECLASSIFICATION_RULES`, `BS_SECTION_ORDER`, `BS_NATIVE_SECTION_MAP`, `BS_ACTIVO_NO_CORRIENTE`, `BS_PASIVO_NO_CORRIENTE`, `BS_SUBTOTAL_LABELS`, `BS_GROUP_TABLES` (all display-only). Materialized `BS_PARTIDA_LABELS` into a literal frozenset of 35 entries to break its dependency on the deleted dicts.
- `backend/config/fields.py`: deleted the orphaned `FIRST_CHAR` constant.
- 10 cuentas land in `POR DEFINIR ACTIVO/PASIVO` (PRESTAMOS / DIETAS ACCIONISTAS, derecho-de-uso provisions). Pre-existing tech debt — old Python pipeline produced the same gap. Tracked in memory at [`project_unclassified_bs_cuentas.md`](../../.claude/projects/-home-administrator-FLXContabilidad/memory/project_unclassified_bs_cuentas.md).

**Commits.** `42c96ed` (Step 1 wiring) + `d1111e4` (Step 2 deletion). Parity was verified end-to-end on prod data: for all four CIAs in May 2025, fetch + prepare + `bs_summary` produced row-identical output to the legacy path, every PARTIDA_BS to-the-centavo.

**Post-ship DDL tweak.** When Phase C / E shipped, `VISTA_BS_PREPARADO.sql` (and `VISTA_PNL_PREPARADO.sql`) gained a `YEAR(FECHA) AS YEAR` column so the SUMARIO views can filter by year directly. Python `fetch_bs_data` / `fetch_pnl_data` still use the `FECHA >= ? AND FECHA < ?` range pattern and don't read the new column — additive change, no Python migration needed.

**Success criteria — met.**
- `git grep -E 'BS_CLASSIFICATION|BS_ACCOUNT_PREFIXES|prepare_bs_stmt|assign_partida_bs|prepare_bs\(' backend/` returns zero hits.
- `load_bs_data` end-to-end works for all four CIAs (verified against 2025/5 prod data).

### Phase C — pre-aggregated summary views  (shipped 2026-05-27)

**Goal.** Push the `pl_summary` / `bs_summary` `GROUP BY` itself into SQL, so the dashboard fetches the summary table directly (~100 rows) instead of fetching row-level prepared data and grouping in pandas.

**Why this is the move that makes concurrent load comfortable on the 5.8 GB box.** Phase A removed Python classification but Flask still pulled 8.4M rows per `(company, year)` and grouped them in pandas. That ~400 MB of pandas state per worker per company was the structural reason concurrent users pushed the box toward OOM. Phase C collapses the summary payload to ~100 rows (~10 KB) — two orders of magnitude smaller. The row-level `df_stmt` / `df_bs` caches still exist (drill-down and BS note tables need them), but they're populated lazily and will be deleted in Phase C+1 once Phase D paginates drill-down. After C the summary path is essentially free; the remaining memory pressure comes from the detail path which Phase D addresses.

This is the work that replaced the former Python-side fact-pickle plan (`docs/FACT_TABLE.md`, deleted 2026-05-22). Same end state (an aggregated payload), better mechanism (database engine instead of Python on our box).

**DDL — shipped to prod 2026-05-25, BS variant patched 2026-05-27.**
- `sql/VISTA_PNL_SUMARIO.sql` — `GROUP BY CIA, YEAR, MES, PARTIDA_PL` with three SALDO columns (`SALDO_TOTAL` / `SALDO_EX_IC` / `SALDO_ONLY_IC`) computed in one pass via `SUM(CASE WHEN IS_INTERCOMPANY = 0/1 THEN SALDO END)`. Filter `IS_STATEMENT_ELIGIBLE = 1` baked in. **One DB roundtrip returns all three IC variants.** ~100 rows per `(CIA, YEAR)`. Deployed to all 5 schemas (4 per-CIA + REPORTES umbrella).
- `sql/VISTA_BS_SUMARIO.sql` — sits on top of `VISTA_BS_PREPARADO_CUMSUM` (Phase E), applies the three reclassification rules + native-section sign flip in CASE expressions, groups to partida-grain. **2026-05-27 patch**: predicate evaluates each row's own `SALDO_CUMSUM` (displayed-month semantics), not the year's last available month. Original `last_month_balance` CTE + `FIRST_VALUE(... ORDER BY MES DESC)` deleted — that produced a ~S/. 39,863 net diff for FIBERLINE 2025/5 on cuentas crossing zero mid-year. Per-cuenta verdict still nets to zero within each section because the sign flip cancels. ~30 rows × 12 months per `(CIA, YEAR)`. Deployed to all 5 schemas.

**Python wiring — shipped 2026-05-27.**
- `backend/data/queries.py` — `fetch_pnl_summary(conn, company, year)` (one call returning all 3 IC variants) + `fetch_bs_summary(conn, company, year)` (partida-level rows × 12 months) + two new identifier constants on the import-time validation tuple.
- `backend/data/fetcher.py` — `fetch_pnl_summary_only` / `fetch_bs_summary_only` connection-handling wrappers, mirroring `fetch_pnl_only` / `fetch_bs_only`.
- `backend/services/accounting/statements.py` — `pl_summary_from_view(summary_df)` returns `{"total", "ex_ic", "only_ic"}` dict; `bs_summary_from_view(summary_df, pl_summary_df=...)` pivots the long-form SQL output and runs `build_pl_rows` / `_build_bs_rows`. NULL-aware POR CLASIFICAR handling: SQL's `SUM(CASE WHEN ... END)` returns NULL when no source rows matched the predicate; we use that as the "drop from this IC variant" signal so the new path matches the old `pl_summary(df_stmt[mask])` contract exactly.
- `backend/services/data_service.py` — 6 call sites rewired (`load_report_data` BS, `_run_pl_summary_only` triple, `_try_pl_stmt_from_disk` PL, `load_pl_data` triple, `load_bs_data` BS). `_run_pl_summary_only` and `_run_pl_transforms` gained `company`/`year` parameters so they can call the SQL helpers themselves.
- Deleted in the same commit: `pl_summary`, `bs_summary`, `_native_section`, `_reclassify_bs_cuentas` in `statements.py`; `BS_RECLASSIFICATION_RULES`, `BS_NATIVE_SECTION_MAP` in `rules.py`.

**Decisions settled during implementation:**
- BS reclassification: **pure SQL** in `VISTA_BS_SUMARIO`. Python's `_reclassify_bs_cuentas` is gone.
- BS reclass timing: **displayed-month semantics** in SQL (matches the spec; differs from prior Python behavior of `vals[-1]`). For mid-flip cuentas Python and SQL disagree by a few thousand PEN that nets to zero within each section. Accepted: BS is pre-production at FLX (not yet used by finance) and the section-balance invariant still holds.
- P&L IC variants: **3 columns in 1 row** — one SQL roundtrip instead of three.
- Parity gate: one-shot Python diff script ([backend/scripts/parity_phase_c.py](../backend/scripts/parity_phase_c.py), git-excluded). P&L: strict to-the-centavo across all 4 CIAs × 2024/2025 — green. BS: section-balance only, warnings logged.

**Drift exposure.** Phase A and B left the summary aggregation in Python as a safety net — if a view's CASE drifted, `pl_summary` would still produce the right number from the row-level data. Phase C removes that safety net. The `POR CLASIFICAR` warning in `prepare_pnl_from_view` is still the early-warning canary for source-data changes; finance users noticing wrong totals on the dashboard is the long-tail backstop.

**Open follow-ups (not blocking Phase C ship):**
- DBA: drop the orphan `[REPORTES].[VISTA_BS_DETALLE]` view (its 4 per-CIA sources were dropped but the umbrella survived). One-shot `DROP VIEW IF EXISTS [REPORTES].[VISTA_BS_DETALLE];`.
- BS imbalances surfaced by the parity script (FIBERLINE 2024 OCT ~S/. 4.3M; NEXTNET 2025 APR/MAY ~S/. 48K; FIBERTECH 2025 JAN-MAY ~S/. 198) are pre-existing pre-prod data issues, not Phase C regressions. Worth investigating before BS goes to finance users.

### Phase D — drill-down via paginated SQL  (the move that unlocks deleting the row-level df cache)

**Goal.** Replace `get_detail_records`'s "filter the in-memory DataFrame" approach with a parameterized SQL query against `VISTA_PNL_PREPARADO` / `VISTA_BS_PREPARADO` plus `OFFSET … FETCH NEXT N ROWS ONLY` pagination. The frontend gets the first page in <1 s plus a `COUNT(*)` total for the row-count hint.

**Why this matters.** Phase C makes the *summary* path beautiful but leaves a 400 MB pandas DataFrame in worker memory just so users can drill into a cell. After Phase D, drill-down goes straight to SQL and the row-level `df` / `pl_stmt` / `bs` caches in `data_service.py` can be deleted — *that's* what makes Phase C+1's memory wins real. Without Phase D, those caches have to stay because drill-down needs them.

**No new DDL.** The existing `VISTA_PNL_PREPARADO` and `VISTA_BS_PREPARADO` views already expose every column the drill-down needs (ASIENTO, NIT, RAZON_SOCIAL, etc.). A wrapper view would only narrow the SELECT list and re-filter `IS_STATEMENT_ELIGIBLE = 1` — both of which the Python caller already does. Adding views just for that is maintenance burden without benefit.

**Steps.**
1. Add `fetch_pnl_detail(conn, company, year, partida, mes=None, filter_col=None, filter_val=None, ic_filter='all', offset=0, limit=500)` to `backend/data/queries.py`. Builds a parameterized query against `REPORTES.VISTA_PNL_PREPARADO` with `WHERE IS_STATEMENT_ELIGIBLE = 1 AND CIA = ? AND YEAR(FECHA) = ? AND PARTIDA_PL = ?` plus optional `MES`, filter, and IC predicates, then `ORDER BY SALDO DESC, ASIENTO, CUENTA_CONTABLE` (the tie-breakers ensure stable pagination) + `OFFSET ? ROWS FETCH NEXT ? ROWS ONLY`.
2. Add `fetch_bs_detail` mirror against `VISTA_BS_PREPARADO`. BS has no eligibility flag, so even simpler.
3. Add `fetch_pnl_detail_count` / `fetch_bs_detail_count` companion functions returning `COUNT(*)` for the same WHERE clause — the frontend uses this to render "showing 500 of 12,345 entries".
4. Rewrite `data_service.get_detail_records` to call the new functions instead of filtering `_caches["df"]`. The `force_refresh=True` foot-gun ([data_service.py:1223](../backend/services/data_service.py#L1223)) goes away because there's no cache to miss.
5. Frontend (`DetailTable`): add a "Load more" button or virtual scroll that bumps `offset` by `limit`. Server-side sort/filter UI is optional — start with what the current UI shows.

**Performance expectation.** A cell that returns 30,000 rows today builds the full 30,000-row JSON list server-side and ships it. Post-Phase-D the first page is 500 rows + a count; ~10× faster on the heavy cells, and the user starts seeing data immediately.

**Order vs Phase C+1.** Phase D lands **before** the Phase C+1 step that deletes the row-level df cache. Otherwise drill-down breaks. Revised order after the 2026-05-28 finding: Phase C ✅ → Phase D ✅ → **Phase F** (migrate section + note tables off the caches) → Phase C+1 (delete the caches).

**Shipped 2026-05-27** (commits `db1bba6` backend + `b07ecae` frontend). `fetch_pnl_detail` / `fetch_bs_detail` + `_count` companions live in `queries.py`; `get_detail_records` is a thin orchestrator routing on `statement_for_view(view_id)`; the route accepts `periods: [{year, month}, ...]` (multi-month / trailing-12M in one query) + `offset`/`limit`. `PLNoteView` + `DetailDataTable` do server-side pagination, single-filter-at-a-time with 300 ms debounce, and an "export all matching rows" path capped at 50 000. **Implementation note:** SQL Server 2017 rejects the `(YEAR, MES) IN ((?,?),...)` row-constructor (error 4145) — the WHERE uses an `(YEAR=? AND MES=?) OR ...` chain instead.

**What Phase D did NOT do (corrected mental model).** Drill-down no longer reads the row-level caches, but the caches are still *written* on every `load_pl_data` / `load_bs_data` because `compute_pl_section` and the BS note tables still read them. So Phase D removed one consumer, not the memory cost. Resident memory is unchanged until Phase F.

### Phase E — BS cumsum view  (DDL shipped 2026-05-25, patched 2026-05-26)

**Goal.** Push the BS cumulative-sum across months into SQL via a window function. The dashboard's BS reports cumulative balances (each month column = "balance as of end of that month"); the cumsum used to happen in pandas on top of the row-level prepared DataFrame. Phase E moves the cumsum into a view; Phase C's `VISTA_BS_SUMARIO` sits on top of it, and once Phase C wiring shipped (2026-05-27) the Python `_apply_bs_cumsum` call inside `bs_summary` was removed alongside `bs_summary` itself. `_apply_bs_cumsum` survives in `aggregation.py` for the BS note-detail tables (`bs_detail_by_cuenta`, `bs_top20_by_nit`), which still operate on row-level data until Phase D.

**View — shipped to prod 2026-05-25.**
- `sql/VISTA_BS_PREPARADO_CUMSUM.sql` — stays at **cuenta-grain** (not partida-grain). Three CTEs:
  1. `months(MES)` — calendar generator emitting 1..12.
  2. `cuenta_years` — one row per `(CIA, YEAR, CUENTA_CONTABLE)` carrying the cuenta's `PARTIDA_BS` / `SECCION_BS` / `DESCRIPCION` attributes.
  3. `monthly` — `GROUP BY (CIA, YEAR, MES, CUENTA_CONTABLE) SUM(SALDO)` from `VISTA_BS_PREPARADO`.
  4. `dense` — `cuenta_years CROSS JOIN months LEFT JOIN monthly` with `COALESCE(SALDO_MENSUAL, 0)`. This **densifies** the input so every cuenta has all 12 months even if there was no activity in a given month.

  Outer SELECT runs `SUM(SALDO_MENSUAL) OVER (PARTITION BY CIA, YEAR, CUENTA_CONTABLE ORDER BY MES ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)` over the dense input. `PARTITION BY YEAR` means cumsum resets at Jan 1 of each year — matches the Python behavior (`fetch_bs_data` always starts at year start). Deployed to all 5 schemas. ~1,500 rows per `(CIA, YEAR)` for FIBERLINE (`121 cuentas × 12 months`).

**2026-05-26 patch — calendar densification.** The original DDL ran the window function directly on the `monthly` CTE, which only had rows for `(cuenta, MES)` pairs that had journal activity in that month. A cuenta like `50.1.1.1.01` (Capital Emitido) booked once on Jan 1 produced exactly one row (`MES=1`), so `VISTA_BS_SUMARIO WHERE MES=5` returned nothing for it and the dashboard's TOTAL ACTIVO for May was ~S/. 4.6M too low across multiple partidas. The patch introduces `months` + `cuenta_years` + `dense` CTEs so that every cuenta gets all 12 months with the cumulative balance correctly carried forward across empty months. Post-patch, TOTAL ACTIVO for FIBERLINE May 2025 went from S/. 11,510,810.47 → S/. 16,126,321.00 (vs Python S/. 16,086,457.31); residual diff is the reclassification-timing semantic gap below + the not-yet-injected `Resultados del Ejercicio`.

**Why cuenta-grain (not partida-grain).** Reclassification rules operate per-cuenta on the cumulative balance. Aggregating to partida first would lose the data needed to apply them. Phase C's `VISTA_BS_SUMARIO` is the partida-grain view that runs on top of this; its `reclassified` CTE evaluates each row's own per-month cumulative balance to apply reclassification before grouping.

**Python caller.** `bs_summary_from_view` (shipped 2026-05-27) queries `VISTA_BS_SUMARIO`, which reads from `VISTA_BS_PREPARADO_CUMSUM` internally. Python never queries `VISTA_BS_PREPARADO_CUMSUM` directly.

**Reclassification timing semantics — resolved 2026-05-27.** Original DDL evaluated the "balance is negative" predicate at the year's last available month via `FIRST_VALUE(SALDO_CUMSUM) OVER (... ORDER BY MES DESC)`. Old Python `_reclassify_bs_cuentas` evaluated it at the displayed month (`vals[-1]` of the displayed value array — effectively DEC for full-year, MAY for partial). The two paths disagreed by S/. 39,863.69 net across TOTAL ACTIVO for FIBERLINE 2025/5 (two pairs that sum to zero within their sections). Resolution: the SQL view was rewritten to displayed-month semantics (the `last_month_balance` CTE + `FIRST_VALUE` window were deleted; the `reclassified` CTE now uses `c.SALDO_CUMSUM` directly). For cuentas crossing zero mid-year the new SQL and old Python disagree by a few thousand PEN that nets to zero within each section — accepted because BS is pre-production at FLX and the section-balance invariant still holds.

### Phase F — migrate P&L section detail + BS note tables to SQL  (the keystone the roadmap was missing)

**Why this phase exists.** Discovered 2026-05-28: the row-level caches (`_caches["df"]` / `pl_stmt` / `pl_preagg` / `pl_preagg_ex_ic` / `pl_preagg_only_ic` / `bs`, ~400 MB per `(company, year)`) are the actual resident-memory cost on the box, and **nothing deletes them yet.** Phase C moved the *summary* off them; Phase D moved *journal-entry drill-down* off them; but two consumers remain:

1. **P&L section detail tables** — `compute_pl_section` ([data_service.py](../backend/services/data_service.py)) builds sales_details / detail_by_ceco / detail_by_cuenta / resultado_financiero splits / etc. from the cached `df_stmt` + three `preagg` frames.
2. **BS note tables** — `bs_detail_by_cuenta` and `bs_top20_by_nit` build the cuenta-grain note tables and NIT top-20 rankings from the cached `df_bs`.

While these read row-level caches, `load_pl_data` / `load_bs_data` must keep *writing* those caches, so the 400 MB stays resident. **Phase C+1 cannot reclaim memory until Phase F moves these two consumers to SQL.**

**Approach (decided 2026-05-28): pre-aggregated SQL views, extending the Phase C pattern.** These tables are grouped aggregates (by CECO, by cuenta, top-N by NIT), not deep journal-entry scrolls, so summary views fit better than Phase-D-style pagination. Build `VISTA_*` views (per-CIA + REPORTES umbrella, same topology) for each section/note grouping; Python fetches the small pre-grouped result instead of grouping a cached DataFrame. Drill-INTO a section cell still uses Phase D's `/api/data/detail` paginated path.

**Steps (sketch — full plan when Phase F is scheduled).**
1. Inventory every grouping `compute_pl_section` and the BS note tables produce; design the minimal set of summary views to cover them (some may share a view with a `GROUP BY` grain parameter).
2. DBA deploys the new views.
3. Wire `compute_pl_section` + the BS note-table builders to fetch from the views; delete the pandas groupby paths once parity is confirmed.
4. Once **no caller reads** `df` / `pl_stmt` / `pl_preagg*` / `bs`, stop writing them. That is the hand-off to Phase C+1.

**Gate.** Per-table parity (the section/note table from SQL must match the pandas output to the centavo) before each deletion, same posture as Phases A–C.

### Phase C+1 — Simplification pass  (depends on Phase F, not just Phase C)

**Why this section exists.** The current architecture — **two co-tenant 3-worker gunicorn stacks (prod + staging) on one 5.8 GB box**, in-memory + disk pickle + single-flight flock — is a multi-layer compromise built around row-level DataFrames being too big to handle naively. The original plan assumed Phase C alone shrank the cached payload to ~10 KB; the 2026-05-28 finding corrected that — **the payload only shrinks once Phase F removes the last row-level consumers.** Phase C+1 is the cleanup that becomes possible *after Phase F*, not after Phase C.

**⚠️ 2026-05-28 co-tenancy finding.** `ps` showed **6 worker processes** on the box: prod master (up 2d 18h) with 3 workers ≈ 1.0 GB RSS, and staging master (up 19h) with 3 workers ≈ 2.4 GB RSS (staging higher because tonight's benchmark + smoke testing filled its caches). Combined ≈ 3.5 GB of 5.8 GB before the OS, SQL ODBC buffers, and headroom. Two independent findings compound here:
- **Each stack over-provisions workers** for ~10–25 internal users (the `workers=3` item below).
- **Running a full second 3-worker stack (staging) on the prod box** roughly doubles the floor. Options to weigh during C+1: drop staging to 1 worker; gate staging behind an env flag so it's only up during active testing; or move staging to a separate small box. This wasn't in the original roadmap — staging was assumed negligible. It is not.

**Conversation trigger (2026-05-22).** While reviewing the post–Phase-A.5 architecture, two architectural questions surfaced that change the picture:

1. *"Why do we have multiple workers if we're going to cache everything?"* — The 3-worker design exists primarily because of memory pressure under the current Python pipeline (each worker independently caches ~400 MB DataFrames). The "smooth out concurrent slow requests" justification is real but quantitatively small for ~10–25 internal finance users. **Phase F** (not Phase C, as originally written) is what eliminates the memory pressure that justifies 3 workers.

2. *"Can we have task-typed workers — one for browsing, one for Excel, one for PDF?"* — Moot as of the server-side export removal: all requests are equivalent dashboard JSON loads, so task-typing no longer has a meaningful axis to split on. Generic workers remain the right call.

**What ships in Phase C+1.** Each item is independent; ship in order of confidence:

1. **Add a request-timeout middleware** that logs (and optionally pages) when any request exceeds ~15 s. Cheap, surfaces problems early, useful regardless of other changes.

2. **Drop `workers = 3` to `workers = 2`** in `backend/gunicorn.conf.py`. Validate the smaller worker count under realistic load (or just in prod with the timeout middleware as the safety net). Memory floor drops by ~400 MB; one worker is still free during any slow request (exports, drill-down). Easy to roll back.

3. **Optional: preload at startup.** Add a small loop at `create_app()` that walks 4 companies × 2 years and calls `load_pl_data` + `load_bs_data` to fill the in-memory cache. Total cached payload post-Phase-C is ~80 KB across all cells, so it can't OOM (unlike `warmup.py` in May which OOMed because the data was 3+ GB). Eliminates the "first user pays" moment entirely. Add only if the natural lazy-fill leaves a real-user-visible cold-cache window.

4. **Remove the disk pickle layer.** Post-Phase-C, summary rows from SQL take <1 s; loading a 10 KB pickle from disk takes microseconds. The disk layer was there as a cold-start optimization for 157 MB pickles — at 10 KB it's pointless. Delete `_save_to_disk`, `_try_pl_stmt_from_disk`, the `.stmt_cache/` directory wiring. Reduces code surface and ops worries (disk-fill, stale pickles).

5. **Remove the single-flight flock.** `_CrossProcLock` was load-bearing when concurrent cold-cache fetches could pull 1.2 GB of duplicate pandas into RAM. Post-Phase-C, concurrent cold-cache fetches each pull ~10 KB; deduplicating sub-second SQL queries isn't worth the fcntl machinery. Keep the in-process `threading.Lock` for the drill-down path. (`_CrossProcLock` and `/tmp/flx_inflight_*.lock` files go away.)

**What stays.**
- **In-memory LRU+TTL cache** in `data_service.py`. Still useful — avoids re-querying SQL for every dashboard click within the 30-min TTL.
- **At least 2 workers.** Even after the server-side Excel/PDF export was removed, a single worker would still mean a slow dashboard load (cold-cache fetch) freezes every other user. 2 workers is the safety floor.
- **Drill-down's row-level path.** Phase C only collapses the summary; drill-down into journal entries still needs row-level rows.

**Architectural posture this leaves us with.**

```
Browser ──▶ Nginx ──▶ Gunicorn (2 sync workers)
                       │
                       ▼
                  in-memory LRU+TTL cache (30-min)
                       │ miss
                       ▼
                  SQL Server (REPORTES.VISTA_PNL_SUMARIO etc.)
                       │
                       ▼  ~100 rows, <1 s
                  back to Flask, build JSON, return
```

Compare to today's stack (3 workers × disk pickle × in-memory × single-flight × scheduler). Phase C+1 removes 3 of those 5 layers.

**Gates.**
- Phase C must be deployed in prod and stable for at least 2 weeks before starting C+1. The current complexity is paying for a real problem that Phase C *should* solve; we want to confirm it actually does under real load before tearing out the safety nets.
- Each C+1 item ships as its own commit so any can be rolled back independently. Order in the list above is suggested order of safety.

**Why not do this now.** Phase C isn't shipped yet. Tearing out the cache layers before the summary views are in production would leave the system in a worse state than today. C+1 is the cleanup that becomes possible *after* the structural fix lands.

## Drift mitigation

With Phase A Step 4 landed, there is no Python fallback. If `VISTA_PNL_PREPARADO` drifts from the rules the team intended, the website silently shows wrong numbers.

**This is a real reduction in safety net** compared to the pre-Phase-A world. We considered keeping `sql/parity_check.py` as a weekly regression job, but the harness only worked by importing the about-to-be-deleted Python pipeline — preserving it would have meant keeping the dead code too. We deleted both.

**What's left to catch drift:**
- The `POR CLASIFICAR` warning emitted by `prepare_pnl_from_view` ([transforms.py](../backend/services/accounting/transforms.py)) when a row arrives with no PARTIDA — currently logs to `backend/logs/error.log`. A spike in those warnings means the ERP added an account code the view doesn't recognize.
- `sql/PARITY_CHECKS.sql` — structural sanity checks (coverage, section consistency, row counts). Run manually after any view DDL change.
- Finance users cross-checking dashboard subtotals against Excel; they tend to notice within a day when a category total shifts.

**If we need a stronger gate in the future**, the right shape is a small SQL-only smoke check: compare PARTIDA-level `SUM(SALDO)` against the previous day's snapshot stored in a `REPORTES.SNAPSHOT_*` table, alert on any partida that swings by >1% without an obvious volume change. That doesn't require resurrecting the deleted Python code.

**What to do if drift is suspected:**
1. Pull the `POR CLASIFICAR` lines from `error.log` — `grep "POR CLASIFICAR" backend/logs/error.log | tail -20`.
2. Look up the offending `CUENTA_CONTABLE` in `VISTA_ANALISIS_CECOS` to see whether it's a legitimate new P&L account or a misclassification.
3. Either extend the view's CASE (DBA round-trip) or have the ERP team correct the source data.

## Classification-gaps surfacing  (follow-up, not in Phase A)

Today 412 rows land in `PARTIDA_PL = 'POR CLASIFICAR'` and ~5,000 BS rows in `POR DEFINIR …`. Net SALDO impact: ~0 PEN. They're visible on the dashboard as a "POR CLASIFICAR" line when non-zero, but easy to overlook. We considered two surfacing strategies:

- **SQL view** (`VISTA_CLASIFICACION_GAPS`) — written then [reverted in `547a793`](https://github.com/Fiberlux-Tech/FLXContabilidadEEFF/commit/547a793). The DDL was never deployed; the file is gone.
- **Python endpoint** (`/api/diagnostics/classification-gaps`) — preferred. Reuses the already-cached prepared DataFrame; one pandas filter, no extra DB roundtrip.

Backlog item — not scheduled. Would ship as a separate PR; nothing else depends on it. The 10 BS cuentas currently in `POR DEFINIR ACTIVO/PASIVO` are tracked separately ([`project_unclassified_bs_cuentas.md`](../../.claude/projects/-home-administrator-FLXContabilidad/memory/project_unclassified_bs_cuentas.md)).

## What's NOT in this roadmap

- Anything related to memory / cache sizing — see [SCALING_ROADMAP.md](SCALING_ROADMAP.md).
- Stored procedures (we deliberately stick to views; no procedural SQL).
- Indexed / materialized views. Phase E's cumsum view runs on a window function over ~6k cuenta-month rows per CIA after the inner GROUP BY — sub-second in practice. If perf ever regresses, indexed views are the escalation path; not needed today.
- Source-view (`VISTA_ANALISIS_CECOS`) changes. Those would need ERP-team coordination and are out of scope for this team.
