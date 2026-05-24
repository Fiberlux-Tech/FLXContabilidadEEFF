# SQL Views Roadmap — push transforms into the database

> **Status**: This is the **active capacity plan** as of 2026-05-24. **Phase A is complete** — P&L classification has moved into `REPORTES.VISTA_PNL_PREPARADO`, all callers are wired to the view, and the old Python pipeline (`prepare_pnl`, `filter_for_statements`, `assign_partida_pl`, `prepare_stmt` + 19 rule constants) and the Python-side parity harness (`sql/parity_check.py`) have been deleted. The SQL view is now the single source of truth for P&L row-level classification. Next up: Phase B (BS migration).
> **Owner**: Backend team. DDL deploys require DBA (current `STERNERO` login is SELECT-only on the new views).
> **Last updated**: 2026-05-24.
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
- **The view enriches, it does not filter.** A row that doesn't belong to the statement (e.g. inventory account `60.x` or the synthetic `79.1.1.1.01`) is still returned by the view, carrying `IS_STATEMENT_ELIGIBLE = 0`. Callers add `WHERE IS_STATEMENT_ELIGIBLE = 1` for the statement; the Excel raw-pivot path uses the unfiltered set. **This is what makes one view serve both surfaces.**
- **Parity must precede deletion.** Phase A's `sql/parity_check.py` compared per-`(CIA, MES, PARTIDA)` `SUM(SALDO)` from the view against the Python pipeline, and gated Step 4 on `PARITY OK ✓` for every year. That harness was deleted alongside Step 4 (the Python pipeline it compared against is gone). For Phase B, validation is structural — `sql/PARITY_CHECKS.sql` plus eyeballing dashboard totals against Excel before the deletion commit lands.

## Roadmap

### Phase A — P&L migration  (shipped 2026-05-24)

**Goal.** P&L classification (`prepare_pnl` → `filter_for_statements` → `assign_partida_pl`) moves from Python to SQL. Python functions and rule constants get deleted from the repo. The view returns enriched rows; eligibility is exposed via the `IS_STATEMENT_ELIGIBLE` flag so the same view feeds the website *and* the Excel raw pivots.

**What is shipped.**

- `sql/VISTA_PNL_PREPARADO.sql` — DDL for 4 per-CIA views + REPORTES umbrella, with `IS_STATEMENT_ELIGIBLE` enrichment, live in DB.
- `backend/data/queries.py:fetch_pnl_data` reads from the view with an `eligible_only` flag (statement path filters to `IS_STATEMENT_ELIGIBLE = 1`; Excel raw-pivot path passes `eligible_only=False`).
- Dashboard ([data_service.py:714](../backend/services/data_service.py#L714)), Excel ([excel/builder.py:110](../backend/services/excel/builder.py#L110)), and PDF ([pdf/builder.py:36](../backend/services/pdf/builder.py#L36)) all call `prepare_pnl_from_view` — a thin dtype adapter — instead of the old classification pipeline.
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

**What's left.** Phase C still references the pre-Phase-A.5 cleanup work — only the "Refresh button stays removed" and "force_refresh ignore plumbing" notes remain as cleanup items. Those are tiny; will fold into Phase B or C.

### Phase B — Balance Sheet migration

**Goal.** Same shape as Phase A, applied to the BS pipeline: `prepare_bs` + `assign_partida_bs` move into `VISTA_BS_PREPARADO`. View returns `SALDO` (sign-aware per asset/liability), `MES`, `PARTIDA_BS`, `SECCION_BS`, and an eligibility flag if needed.

**What is shipped today.**
- `sql/VISTA_BS_PREPARADO.sql` — DDL committed but **not deployed yet**.

**Open question / DBA decision.** Before redeploying BS, decide whether the same enrichment-not-filtering pattern applies. Current draft excludes only `FUENTE LIKE 'CIERRE%'` and filters to class 1-5 — there's no `>=619`-style scope rule, so the view is naturally permissive already. Likely no `IS_STATEMENT_ELIGIBLE` needed for BS.

**Out of scope for Phase B** (deferred to Phase C):
- Cumulative `SUM` across months (`statements.py bs_summary` cumsum).
- Reclassification rules: BS accounts that move sections when end-of-period balance is negative (`BS_RECLASSIFICATION_RULES`).
- `UTILIDAD NETA` injection from P&L into BS PATRIMONIO.
- `CORRIENTE` / `NO CORRIENTE` sub-section split.

Each of these is order-sensitive against the cumsum and likely needs a stored function or a Python passthrough. Worth doing in pieces, not as one mega-view.

**Steps.**
1. **DBA**: deploy `sql/VISTA_BS_PREPARADO.sql`.
2. Run `sql/PARITY_CHECKS.sql` and eyeball the dashboard / Excel BS totals against a known-good month before and after wire-up. (The Python-side parity harness from Phase A is gone; there is no automated numeric gate for Phase B.)
3. Wire `fetch_bs_data` and `prepare_bs_stmt` callers to the view.
4. Delete `prepare_bs`, `assign_partida_bs`, BS-related constants (`BS_CLASSIFICATION`, `BS_CLASSIFICATION_OVERRIDES`, `BS_NATIVE_SECTION_MAP`, etc. — but **keep** `BS_PARTIDA_ORDER`, `BS_GROUP_TABLES`, `BS_SECTION_ORDER`, `BS_PARTIDA_LABELS`, `BS_ACTIVO_NO_CORRIENTE`, `BS_PASIVO_NO_CORRIENTE`; those are display ordering not classification).

### Phase C — pre-aggregated summary views  (load-bearing for concurrency)

**Goal.** Push the `pl_summary` / `bs_summary` `GROUP BY` itself into SQL, so the dashboard fetches the summary table directly (~100 rows) instead of fetching row-level prepared data and grouping in pandas.

**Why this is the move that makes concurrent load comfortable on the 5.8 GB box.** Phase A removes Python classification but Flask still pulls 8.4M rows per `(company, year)` and groups them in pandas. That ~400 MB of pandas state per worker per company is the structural reason concurrent users push the box toward OOM. Phase C collapses the payload to ~100 rows (~10 KB) — two orders of magnitude smaller. After C:

- Each cached `(company, year)` summary is small enough that per-worker duplication stops mattering. Three workers holding the same FIBERLINE summary is ~30 KB total, not ~1.2 GB.
- The disk pickle layer (kept as a cold-start optimization) becomes ~10 KB per cell, so first-click pickle loads drop from 5–15 s to milliseconds.
- Per-request CPU drops further; the `GROUP BY` runs in the SQL engine where it's both fast and outside our memory budget.

This is the work that replaced the former Python-side fact-pickle plan (`docs/FACT_TABLE.md`, deleted 2026-05-22). Same end state (an aggregated payload), better mechanism (database engine instead of Python on our box).

**Sequencing note.** Phase A and B (classification) must land first because Phase C is `GROUP BY … PARTIDA_PL` / `PARTIDA_BS`, and PARTIDA is what A and B materialize. Don't start C until A/B are wired and parity is proven; otherwise drift in the classification rules between Python and SQL would surface as drift in the summary totals, which is much harder to debug.

**Candidate views.**
- `REPORTES.VISTA_PNL_SUMARIO` — `GROUP BY CIA, MES, PARTIDA_PL` with `IS_INTERCOMPANY` filter variants (or three columns: total, ex_ic, only_ic).
- `REPORTES.VISTA_BS_SUMARIO_CUMSUM` — `GROUP BY CIA, PARTIDA_BS, SECCION_BS, MES` with `SUM(SUM(SALDO)) OVER (PARTITION BY … ORDER BY MES)` to do cumsum inside the view. Tricky because reclassification rules depend on the cumulative balance — see Phase B "out of scope" above. If the cumsum-plus-reclassification combination doesn't cleanly factor into a view, fall back to a "cumsum view + Python reclassification" hybrid; the cumsum alone is the expensive part.

**Drift exposure.** Phase A and B left the summary aggregation in Python as a safety net — if a view's CASE drifted, `pl_summary` would still produce the right number from the row-level data. Phase C removes that safety net. Since the Python-side parity harness was deleted in Phase A Step 4, before Phase C deletes the Python `pl_summary` path, a new parity check needs to be written that compares the summary view output against the in-memory `pl_summary` output for a baseline month — and stays green for two weeks of dashboard use. Cheaper to author at C time than to preserve the old harness through B.

**Cleanup that didn't fit in A.5.** The scheduler code was deleted in Phase A.5, but a few small follow-ups remain — fold into Phase B or C, whichever ships next:

- Delete the `force_refresh` ignore plumbing that the scheduler PR introduced (the Refresh button stays removed; that change was independently correct).
- Remove any stale `/tmp/flx_refresh.lock` on the host (one-off cleanup).
- Update [docs/ARCHITECTURE.md](ARCHITECTURE.md) caching-strategy section to reflect on-demand cache-fill as the single design.

### Phase D — detail-table push-downs  (probably not worth it)

**Goal.** Make `detail_by_ceco`, `detail_by_cuenta`, `detail_ceco_by_cuenta`, etc. into SQL views that the user can pull directly.

**Why probably not.** These run on already-cached `df_stmt` in memory; pandas grouping on prepared data is fast (sub-100 ms). The benefit would be removing the in-memory pivot cache (`preagg`) — small RAM win, not a latency win. Revisit only if the SCALING_ROADMAP memory budget gets tighter.

### Phase C+1 — Simplification pass  (queued, depends on Phase C in prod)

**Why this section exists.** The current architecture — 3 sync gunicorn workers, in-memory + disk pickle + single-flight flock, scheduled-refresh-then-on-demand-fill — is a multi-layer compromise built around row-level DataFrames being too big to handle naively. Phase C removes the size problem at its source: the cached payload becomes ~10 KB per `(company, year)` instead of ~400 MB. **Most of the surrounding complexity exists to compensate for a problem Phase C deletes.** Once Phase C is in prod and stable, the system can shed several layers without losing anything.

**Conversation trigger (2026-05-22).** While reviewing the post–Phase-A.5 architecture, two architectural questions surfaced that change the picture:

1. *"Why do we have multiple workers if we're going to cache everything?"* — The 3-worker design exists primarily because of memory pressure under the current Python pipeline (each worker independently caches ~400 MB DataFrames). The "smooth out concurrent slow requests" justification is real but quantitatively small for ~10–25 internal finance users. Phase C eliminates the memory pressure, which removes the dominant reason for 3 workers.

2. *"Can we have task-typed workers — one for browsing, one for Excel, one for PDF?"* — Yes, the pattern exists (nginx split-routing or Celery), but the traffic profile here doesn't justify the operational complexity (two systemd units or a new Redis/RabbitMQ dependency, frontend polling changes, ~400 MB extra Python memory floor). Internal tool, sparse traffic, occasional exports — generic workers are the right call. **Decision: do not pursue task-typed workers.** Revisit only if export volume grows significantly or a new heavy endpoint appears.

**What ships in Phase C+1.** Each item is independent; ship in order of confidence:

1. **Add a request-timeout middleware** that logs (and optionally pages) when any request exceeds ~15 s. Cheap, surfaces problems early, useful regardless of other changes.

2. **Drop `workers = 3` to `workers = 2`** in `backend/gunicorn.conf.py`. Validate the smaller worker count under realistic load (or just in prod with the timeout middleware as the safety net). Memory floor drops by ~400 MB; one worker is still free during any slow request (exports, drill-down). Easy to roll back.

3. **Optional: preload at startup.** Add a small loop at `create_app()` that walks 4 companies × 2 years and calls `load_pl_data` + `load_bs_data` to fill the in-memory cache. Total cached payload post-Phase-C is ~80 KB across all cells, so it can't OOM (unlike `warmup.py` in May which OOMed because the data was 3+ GB). Eliminates the "first user pays" moment entirely. Add only if the natural lazy-fill leaves a real-user-visible cold-cache window.

4. **Remove the disk pickle layer.** Post-Phase-C, summary rows from SQL take <1 s; loading a 10 KB pickle from disk takes microseconds. The disk layer was there as a cold-start optimization for 157 MB pickles — at 10 KB it's pointless. Delete `_save_to_disk`, `_try_pl_stmt_from_disk`, the `.stmt_cache/` directory wiring. Reduces code surface and ops worries (disk-fill, stale pickles).

5. **Remove the single-flight flock.** `_CrossProcLock` was load-bearing when concurrent cold-cache fetches could pull 1.2 GB of duplicate pandas into RAM. Post-Phase-C, concurrent cold-cache fetches each pull ~10 KB; deduplicating sub-second SQL queries isn't worth the fcntl machinery. Keep the in-process `threading.Lock` for the drill-down path. (`_CrossProcLock` and `/tmp/flx_inflight_*.lock` files go away.)

**What stays.**
- **In-memory LRU+TTL cache** in `data_service.py`. Still useful — avoids re-querying SQL for every dashboard click within the 30-min TTL.
- **At least 2 workers.** Excel and PDF exports are still ~5–10 s of CPU-bound rendering work (in `openpyxl` / `fpdf2`, not in data fetch). Dropping to 1 worker would mean every export freezes every other user. 2 workers is the safety floor.
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

Will ship as a separate PR after Phase A's deletion lands.

## What's NOT in this roadmap

- Anything related to memory / cache sizing — see [SCALING_ROADMAP.md](SCALING_ROADMAP.md).
- Stored procedures (we deliberately stick to views; no procedural SQL).
- Indexed / materialized views (would help cumsum-heavy Phase C; out of scope until then).
- Source-view (`VISTA_ANALISIS_CECOS`) changes. Those would need ERP-team coordination and are out of scope for this team.
