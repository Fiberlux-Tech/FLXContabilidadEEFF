# Phase 2 — Monthly Fact Table

> **Status**: Plan revised 2026-05-14 after confirming `REPORTES.VISTA_ANALISIS_CECOS` is live (changes posted by finance appear immediately). Not yet implemented.
> **Owner**: Backend team. No DBA dependency.
> **Supersedes**: [SCALING_ROADMAP.md](SCALING_ROADMAP.md) Phase 2 section — that section is the agreement; this doc is the implementation spec.
> **Depends on**: [SCHEDULED_REFRESH.md](SCHEDULED_REFRESH.md) shipped and stable. Phase 2 closes the "Known limitation: per-worker pickle reload" left open by the scheduler.
> **Last updated**: 2026-05-14.

## Why

The scheduled refresh eliminated DB queries on user requests. What it did not eliminate, and could not by design, is the **per-worker pickle-load cost** that fires every time a user's HTTP request lands on a gunicorn worker that hasn't yet deserialized the requested `(company, year)` DataFrame. Observed on staging 2026-05-14: 5–15 seconds of pandas deserialization per cold worker for the largest companies (FIBERLINE, FIBERTECH). With 3 workers and no session stickiness, users hit cold workers often during the first ~10 minutes after a deploy or restart.

The pickles are big because `df_stmt` contains row-level journal entries: ~165 MB for FIBERLINE_2025 (verified via `ls -la backend/services/.stmt_cache/`). The summary endpoints that the dashboard hits on every page load do not need row-level data — they aggregate everything by `(CIA, ANIO, MES, CUENTA_CONTABLE, CENTRO_COSTO)`. A pre-aggregated fact table at that grain shrinks each pickle ~16× to roughly 10 MB. Pickle load drops from ~10 s to <1 s, well below user-noticeable.

> **What Phase 2 does NOT touch**: detail drill-down (clicking into a number to see the underlying journal entries) still needs row-level data. That path keeps calling `fetch_pnl_data` and `fetch_pnl_only`. Only the *summary* path moves to the fact table. The BS path is also out of scope — Phase 2 ships a P&L fast path only.

**User experience after Phase 2**: a cold-worker first click on any company drops from ~10 s to <1 s. Subsequent clicks on the same worker stay sub-second as today. Freshness contract is preserved — summary, BS, and drill-down all reflect data at most one hour old, same as today's scheduler. No "data as of yesterday" footer; nothing changes from the user's perspective except speed.

## Freshness contract (the constraint that drives this design)

`REPORTES.VISTA_ANALISIS_CECOS` is a **live view**: journal entries posted by the finance team appear in the view, and therefore in the dashboard's drill-down, immediately. Today's hourly scheduler caches that live data on a 60-minute window for the summary and BS paths. The whole dashboard shares one freshness clock: **at most 1 hour old**.

This is non-negotiable for Phase 2. If the summary path's clock drifts past 1 hour — say, to "data as of last night at 02:00" — users would see P&L totals that don't match the sum of journal entries visible in drill-down beneath them. That's a regression worse than the cold-worker latency Phase 2 is trying to fix.

**Consequence**: any fact table we build must be **rebuilt hourly**, not nightly. The original (2026-05-13) version of this doc proposed nightly because it modeled the fact table after a typical DBA-owned data-warehouse artifact. That was wrong for our freshness contract. This revision corrects it.

## How we build it (one path, not two)

We build the fact table **ourselves**, on **our** server, **hourly**. No DBA conversation, no SQL Agent jobs, no SQL Server permissions beyond what we already have.

### What we already have

- Read access to `REPORTES.VISTA_ANALISIS_CECOS` via the existing pyodbc connection pool ([backend/data/queries.py:15](../backend/data/queries.py#L15)).
- A daemon-thread scheduler pattern at [backend/services/refresh_scheduler.py](../backend/services/refresh_scheduler.py) (159 lines) that already runs hourly between 7am and 9pm Lima and reads from the view 15 times a day.
- A disk cache directory at `backend/services/.stmt_cache/` with the `{kind}_{company}_{year}.pkl` naming convention.

### What we add

- A small **SQLite database** at `backend/data/fact_table.db` (or a directory of pickle files — see "Storage choice" below). Holds one row per `(CIA, ANIO, MES, CUENTA, CECO)` per company-year. Estimated size: ~10 MB total across all 4 companies × 2 years. Trivial.
- An **hourly ETL** built into the existing scheduler. The current scheduler at [refresh_scheduler.py](../backend/services/refresh_scheduler.py) already runs each hour and for each company calls `invalidate_cache → load_pl_data → load_bs_data`. We modify it (or extend it) to also write the aggregated rows out to the fact table during each cycle. **No new daemon, no new schedule.**
- A **fast-path read function** `fetch_pnl_summary_fast(company, year)` that reads from our SQLite/pickles instead of from the SQL Server view.
- A **per-company feature flag** so we can flip companies one at a time during rollout, with rollback per company.

### What we do NOT add

- No new SQL artifact on the DBA's server.
- No DBA kickoff meeting.
- No "Path A vs Path B" decision tree.
- No new SQL Agent jobs.
- No additional reads of `VISTA_ANALISIS_CECOS` — the scheduler already reads it 15× per day; the ETL piggybacks on those existing reads.

### Storage choice: SQLite vs. pickles

Either works. Default to **pickles** (`fact_{company}_{year}.pkl` in `.stmt_cache/`) because:

- Symmetric with the existing disk cache convention.
- No new database driver, no schema migration tooling, no concurrent-writer concerns.
- Read by `pd.read_pickle` in <100 ms (the file is ~10 MB), well below the latency budget.
- The existing `_save_to_disk` / `_try_pl_stmt_from_disk` helpers at [data_service.py:264](../backend/services/data_service.py#L264) generalize to a new `kind="fact"` value with no structural change.

Only switch to SQLite if a future requirement needs cross-row queries against the fact (e.g., "show me all accounts where DEBITO > 1M across all companies"). The summary path does not need that.

## What about the original Path A?

Path A in the earlier revision proposed asking the DBA to build the fact table on their side via a SQL Agent job. **That is dropped from this plan.** Two reasons:

1. **It doesn't help freshness.** A DBA-owned SQL Agent job rebuilds on whatever schedule the DBA agrees to. Hourly isn't a typical SQL Agent cadence — they'd need a recurring "every 60 min, 8am–10pm Lima" job, which is a non-standard ask. Even if granted, we don't gain anything over building it ourselves on the same cadence.
2. **It adds latency to changes.** Any tweak to the fact table's grain, filtering, or schema requires a DBA ticket. Owning the ETL means we can change the schema by editing one Python file and redeploying.

Path A might still be worth pursuing later if Phase 4 (DBA index work) reveals that the underlying tables behind the view need indexes the DBA hasn't built. But that's a separate conversation; the fact table doesn't need it.

## Architecture

### Fact-table shape (on disk)

Stored as pickle files in `backend/services/.stmt_cache/`, one per company per year.

```
backend/services/.stmt_cache/fact_FIBERLUX_2025.pkl     ~2 MB
backend/services/.stmt_cache/fact_FIBERLUX_2026.pkl     ~1 MB
backend/services/.stmt_cache/fact_FIBERTECH_2025.pkl    ~5 MB
... (one per company per year, 8 files total)
```

Each pickle holds a pandas DataFrame at the grain `(CIA, ANIO, MES, CUENTA_CONTABLE, CENTRO_COSTO)` with columns matching the existing row-level fetch's column set so the downstream pipeline runs unchanged:

| Column            | Source                                                 |
|-------------------|--------------------------------------------------------|
| `CIA`             | grain key                                              |
| `ANIO`            | grain key                                              |
| `MES`             | grain key                                              |
| `CUENTA_CONTABLE` | grain key                                              |
| `CENTRO_COSTO`    | grain key                                              |
| `DEBITO_LOCAL`    | `SUM(DEBITO_LOCAL)` over the grain                     |
| `CREDITO_LOCAL`   | `SUM(CREDITO_LOCAL)` over the grain                    |
| `FECHA`           | synthesized as `date(year, MES, 1)`                    |
| `DESCRIPCION`     | first non-null value per cuenta (cardinality is finite)|
| `DESC_CECO`       | first non-null value per ceco                          |
| `NIT`             | empty string (summary path doesn't read it)            |
| `RAZON_SOCIAL`    | empty string                                           |
| `ASIENTO`         | empty string                                           |

The CIERRE filter (`FUENTE NOT LIKE 'CIERRE%'`, today at [queries.py:57](../backend/data/queries.py#L57)) is applied in the SQL that reads the view, **before** the aggregation runs. Same semantics as today's `fetch_pnl_data`.

> **Why not pre-derive `PARTIDA_PL` and `IS_INTERCOMPANY` into the fact-table columns?** Because [assign_partida_pl](../backend/services/accounting/transforms.py#L97) and the `IS_INTERCOMPANY` derivation at [transforms.py:152-154](../backend/services/accounting/transforms.py#L152) are SACRED. Materializing them in the ETL forks the definition. Keep the columns at their raw grain (`CUENTA_CONTABLE`, `CENTRO_COSTO`) and let the Python layer derive both — the small aggregated DataFrame is still ~10 MB; the derivation runs in microseconds.

### Hourly ETL (extending the existing scheduler)

The existing scheduler at [refresh_scheduler.py](../backend/services/refresh_scheduler.py) already runs each hour during 7am–9pm Lima and reads `VISTA_ANALISIS_CECOS` for each `(company, year)` cell. We extend its `_refresh_cycle` body to also write the aggregated fact pickle for each cell:

```
for each (company, year) in smallest-first order:
    invalidate_cache(company, year)
    raw = fetch_pnl_data(company, year)                  # row-level, same as today
    fact = raw.groupby([CIA, ANIO, MES, CUENTA, CECO]).agg(...)
    pd.to_pickle(fact, ".stmt_cache/fact_{company}_{year}.pkl")
    load_pl_data(company, year)                          # populates in-memory caches
    load_bs_data(company, year)
```

**This piggybacks on existing work.** We don't add a second daemon thread, a second flock, or a second schedule. The aggregation step adds <1 s per company-year — negligible relative to the existing 5–10 min cycle.

**Window**: the existing scheduler runs 07:00–21:00. If you want 08:00–22:00, that's a one-line change at [refresh_scheduler.py](../backend/services/refresh_scheduler.py) (constant `_REFRESH_HOURS`). Independent of the fact-table decision.

### New fast-path read function

| Function | Lives in | Replaces (when flag is on) | Returns |
|----------|----------|---------------------------|---------|
| `fetch_pnl_summary_fast(company, year)` | `backend/data/queries.py` (new, alongside `fetch_pnl_data`) | [fetch_pnl_only](../backend/data/fetcher.py#L169) | Aggregated DataFrame from `fact_{company}_{year}.pkl` |

This function returns a DataFrame with the column set listed in "Fact-table shape" above. The downstream pipeline (`_run_pl_summary_only` → `prepare_stmt` → `pl_summary`) sees the same shape it does today and runs unchanged.

### Per-company feature flag

Four environment variables, default false. Pattern mirrors `STRICT_BS_BALANCE` at [backend/config/settings.py:60](../backend/config/settings.py#L60):

```
USE_FACT_TABLE_FIBERLUX=true
USE_FACT_TABLE_FIBERTECH=true
USE_FACT_TABLE_FIBERLINE=true
USE_FACT_TABLE_NEXTNET=true
```

## Implementation

File-by-file. Lines refer to the staging tree at the time this doc was written (2026-05-14); verify with `sed -n '<line>p' <file>` before editing.

### New addition to `backend/data/queries.py`

Add `fetch_pnl_summary_fast(company, year)` after [fetch_pnl_data](../backend/data/queries.py#L79). Reads from disk, not from the SQL view:

```python
def fetch_pnl_summary_fast(company: str, year: int) -> pd.DataFrame:
    """Fast P&L summary fetch from the hourly-built fact pickle.

    Returns rows at (CIA, ANIO, MES, CUENTA, CECO) grain, shaped to match
    the existing fetch_pnl_data column set so downstream transforms are
    unchanged. Used only on the summary path; drill-down keeps using
    fetch_pnl_data.

    Raises FileNotFoundError if the fact pickle is missing (the scheduler
    hasn't built it yet; caller falls back to fetch_pnl_data).
    """
    path = STMT_CACHE_DIR / f"fact_{company}_{year}.pkl"
    return pd.read_pickle(path)
```

No SQL connection needed — the pickle is local. The scheduler is responsible for keeping it fresh.

### Edit: `backend/services/refresh_scheduler.py` — extend the cycle to write fact pickles

The existing scheduler at [refresh_scheduler.py](../backend/services/refresh_scheduler.py) runs each hour and walks all `(company, year)` cells. Extend its per-cell body to write the fact pickle after the row-level data has been fetched:

```python
# Existing per-cell body (paraphrased from refresh_scheduler._refresh_cycle):
invalidate_cache(company, year)
load_pl_data(company, year)        # populates df_stmt cache + disk pickle
load_bs_data(company, year)

# New: also write the fact pickle.
df_stmt = _caches["pl_stmt"].get(company, year)
if df_stmt is not None:
    fact = _aggregate_to_fact(df_stmt)
    _save_to_disk(company, year, fact, kind="fact")
```

`_aggregate_to_fact` is a new helper (~15 lines) that groups by the grain keys and sums DEBITO_LOCAL / CREDITO_LOCAL. It lives in `data_service.py` next to `_save_to_disk`.

### Edit: `backend/config/settings.py`

Extend `Config` dataclass at [settings.py:38-43](../backend/config/settings.py#L38) with one boolean per company (4 fields), and parse them in `get_config()` at [settings.py:57](../backend/config/settings.py#L57). Pattern follows `strict_bs_balance` at line 60. Add a helper:

```python
def use_fact_table_for(self, company: str) -> bool:
    """True iff the per-company flag is set for this company."""
    ...
```

The helper lives on `Config` so `_ensure_pl_stmt_cached` reads it with one call.

### Edit: `backend/services/data_service.py`

The intercept lives in [_ensure_pl_stmt_cached](../backend/services/data_service.py#L793). Today:

```python
raw = fetch_pnl_only(company, year)
```

Becomes:

```python
if get_config().use_fact_table_for(company):
    try:
        raw = fetch_pnl_summary_fast(company, year)
        logger.info("P&L fetch (fast path): %.2fs (%d rows)", time.perf_counter() - t0, len(raw))
    except FileNotFoundError:
        # Fact pickle not built yet (first boot before scheduler runs).
        # Fall through to the row-level path; the next scheduler cycle
        # will populate the pickle.
        logger.warning("fact pickle missing for %s/%d; falling back to row-level", company, year)
        raw = fetch_pnl_only(company, year)
else:
    raw = fetch_pnl_only(company, year)
    logger.info("P&L fetch: %.2fs (%d rows)", time.perf_counter() - t0, len(raw))
```

Everything downstream of this — `_run_pl_summary_only(raw)` and the `_caches[...].set(...)` / [_save_to_disk](../backend/services/data_service.py#L264) calls — runs unchanged. The `df_stmt` pickle that gets cached after `prepare_stmt` is now ~10 MB instead of ~150 MB for FIBERLINE, which is exactly the point: the cold-worker pickle-load drops from ~10 s to <1 s.

Intercepting in `_ensure_pl_stmt_cached` rather than separately in `load_pl_data` and `load_bs_data` (the handoff prompt's literal phrasing) is a deliberate simplification: `load_pl_data` at [data_service.py:888](../backend/services/data_service.py#L888) and `load_pl_section` at [data_service.py:947](../backend/services/data_service.py#L947) both go through this single helper. One intercept point, two consumers covered.

### New file: `backend/scripts/diff_fact_vs_view.py`

Single-shot validation harness. Layout mirrors [backend/scripts/manage_users.py](../backend/scripts/manage_users.py): `argparse`, logging to stdout, exit code 0 on zero diffs, non-zero on any non-zero diff. Outline:

```python
def main():
    args = parse_args()  # --company, --year, --month (optional)
    diffs = []
    for company in args.companies:
        for year in args.years:
            for month in args.months or range(1, 13):
                row_path = _run_row_level(company, year, month)
                fast_path = _run_fast(company, year, month)
                diff = _compare(row_path, fast_path)  # (PARTIDA_PL, month) grain
                if not diff.empty:
                    diffs.append((company, year, month, diff))
    if diffs:
        _print_diffs(diffs)
        sys.exit(1)
    sys.exit(0)
```

The script imports from `services.data_service` and toggles the flag in-process by mutating an env var before calling — it does **not** restart gunicorn. Run from the staging tree CLI before flipping each company's flag in production.

### Frontend: no new UI

Freshness is unchanged from today's scheduler (~1 hour). The dashboard already serves whatever the scheduler last loaded; users perceive no difference in freshness, only in speed. **No "data as of" footer is needed** — adding one would invite confusion about a staleness window that hasn't changed.

If a follow-up project later wants a freshness indicator, that can be its own work; it isn't part of Phase 2.

## Validation

### Diff harness must show zero diffs

For every `(company, year, month)` triple across `{FIBERLINE, FIBERLUX, FIBERTECH, NEXTNET} × {2025, 2026} × {1..12}`, the diff harness runs both code paths and compares output at the `(PARTIDA_PL, month)` grain for three pivots: `pl_summary`, `pl_summary_ex_ic`, `pl_summary_only_ic`.

> **What counts as "bit-identical"**: zero non-zero rows in the elementwise diff at the `(PARTIDA_PL, month)` grain for all three pivots. We compare *summed measures*, not raw row counts — row counts will not match because the fact table is aggregated. If a diff is non-zero, fix the fact table SQL (typically a missed `FUENTE NOT LIKE 'CIERRE%'` filter or a sign-convention drift on a specific account), not the harness threshold.

### Per-company rollback

If a regression surfaces after a per-company flag flip on prod, set the corresponding `USE_FACT_TABLE_<COMPANY>=false` in `.env`, restart the service (`sudo systemctl restart flxcontabilidad`), validate that the dashboard re-serves correct numbers from the row-level path, file an issue for the underlying aggregation fix. Other companies' flags stay on. The disk pickle cache should be invalidated on rollback so subsequent fetches re-populate from the live view; verify [invalidate_cache](../backend/services/data_service.py#L223) clears both `df_stmt_*` and the new `fact_*` pickles before shipping.

## Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| **SACRED drift via the aggregation step.** A `groupby + sum` in the ETL may behave differently from pandas `sum` after `prepare_stmt`: NULL handling, decimal rounding, CIERRE filter applied at the wrong stage. | Medium pre-validation, zero after diff harness passes | High | Diff harness must be zero for every `(company, year, month)` triple. No exceptions. If diffs are non-zero, fix the aggregator, never the threshold. |
| **Stale fact pickle when scheduler skips a cycle** (e.g., DB outage during 14:00 cycle leaves the 13:00 pickle in place). | Low | Low | Same risk applies today to the row-level pickle. The scheduler logs its outcome per cell; spot-check after deploys. No new exposure. |
| **First-boot race**: gunicorn starts, a user request lands before the first scheduler cycle has built the fact pickle. | Medium during initial deploy | Low | The intercept code falls back to the row-level path on `FileNotFoundError`. The user pays a one-time cold-fetch cost; the next scheduler cycle populates the pickle and subsequent requests hit the fast path. |
| **`IS_INTERCOMPANY` derivation drift** if the aggregation step accidentally drops CUENTA or CECO from the grain. | Very low (grain explicitly includes both) | High | Diff harness catches it; the assertion is at the `(PARTIDA_PL, month)` grain after the SACRED derivation. |
| **Flag-flip inconsistency across workers** if `.env` is reloaded mid-flight. | Low | Medium | Env vars are read at boot only. Restart is the contract; documented in DEPLOYMENT.md. |
| **CIERRE-filter parity broken** in the aggregation step. | Medium pre-validation | High | Diff harness catches it. The ETL reads `df_stmt` *after* `prepare_stmt` has already applied the filter via [queries.py:57](../backend/data/queries.py#L57), so we inherit the correct filter for free. |
| **Disk-pickle staleness on flip-back.** If we flip a company off, the `fact_*.pkl` is no longer the authoritative cached representation; the row-level path doesn't read it. | Low | Low | `invalidate_cache(company, year)` already clears the per-`(company, year)` slot. Confirm `_delete_disk_cache` includes the `fact` kind before shipping. |
| **Scheduler cycle time grows** by the cost of the aggregation step. | Very low (aggregation is sub-second vs. ~10 min cycle) | None | No mitigation needed; measure on staging soak. |

## Rollout

In order, with go/no-go gates between steps. **No DBA dependency** — every step is in our hands.

1. **Scheduler ETL extension + fast-path code + flag + diff harness on `dev`** (~2 days). Edits to `queries.py`, `fetcher.py`, `settings.py`, `data_service.py`, `refresh_scheduler.py`, plus new `backend/scripts/diff_fact_vs_view.py`. Commit message: `feat(fact-table): hourly P&L summary fact pickles behind per-company flags`.
2. **Staging deploy + soak one scheduler cycle** (~1 day). Confirm fact pickles appear in `.stmt_cache/` after the next hourly cycle; spot-check file sizes (~10 MB or less).
3. **Diff harness validates zero diffs across all triples** (~1 day). Run on staging with all 4 flags toggled on in-process. Zero diffs is the gate. If any diff is non-zero, return to step 1 — fix the aggregator.
4. **Per-company flip + 48 h soak on staging**, in order:
   - FIBERLUX (smallest, lowest blast radius)
   - NEXTNET
   - FIBERTECH
   - FIBERLINE
5. **Promote to prod** via `./promote.sh` from the prod tree per [DEPLOYMENT.md](DEPLOYMENT.md). Same flag flips repeated on prod, 48 h soak per company. Promotion of each flag is a `.env` edit on prod plus `sudo systemctl restart flxcontabilidad`.

## Effort and timeline

| Item                                                                            | Days | Owner |
|---------------------------------------------------------------------------------|------|-------|
| Scheduler ETL extension + `fetch_pnl_summary_fast` + flag wiring + intercept    | 2.0  | Ours  |
| Diff harness + cross-company validation                                         | 1.0  | Ours  |
| Per-company rollout + 48 h soak each                                            | ~10 days elapsed (~2 days active) | Ours |
| **Ours, active**                                                                | **~5 days**       | |
| **Elapsed, dominated by per-company soak windows**                              | **~2 weeks**      | |

## What this doc is not

This doc is not a BS fast path. Phase 2's scope is P&L summary only; a BS equivalent could follow if the same pickle-load problem materializes there, but Phase 2 ships P&L alone.

This doc is not a replacement for [SCHEDULED_REFRESH.md](SCHEDULED_REFRESH.md). The scheduler still fires hourly; the fact table just makes each fetch + serialize cycle dramatically cheaper. Both layers stay.

This doc is not a Redis reintroduction. If finance flags the nightly staleness window as too coarse for summary use, Phase 1 (Redis-backed cache from [SCALING_ROADMAP.md](SCALING_ROADMAP.md)) stays available as the next architectural unlock. Phase 2 is orthogonal to it.
