# Phase 2 — Monthly Fact Table

> **Status**: Plan agreed 2026-05-14. Not yet implemented.
> **Owner**: Backend team + DBA team (Path A) or Backend team alone (Path B).
> **Supersedes**: [SCALING_ROADMAP.md](SCALING_ROADMAP.md) Phase 2 section — that section is the agreement; this doc is the implementation spec.
> **Depends on**: [SCHEDULED_REFRESH.md](SCHEDULED_REFRESH.md) shipped and stable. Phase 2 closes the "Known limitation: per-worker pickle reload" left open by the scheduler.
> **Last updated**: 2026-05-14.

## Why

The scheduled refresh eliminated DB queries on user requests. What it did not eliminate, and could not by design, is the **per-worker pickle-load cost** that fires every time a user's HTTP request lands on a gunicorn worker that hasn't yet deserialized the requested `(company, year)` DataFrame. Observed on staging 2026-05-14: 5–15 seconds of pandas deserialization per cold worker for the largest companies (FIBERLINE, FIBERTECH, CONSOLIDADO). With 3 workers and no session stickiness, users hit cold workers often during the first ~10 minutes after a deploy or restart.

The pickles are big because `df_stmt` contains row-level journal entries: ~165 MB for FIBERLINE_2025, ~257 MB for CONSOLIDADO_2025 (verified via `ls -la backend/services/.stmt_cache/`). The summary endpoints that the dashboard hits on every page load do not need row-level data — they aggregate everything by `(CIA, ANIO, MES, CUENTA_CONTABLE, CENTRO_COSTO)`. A pre-aggregated fact table at that grain shrinks each pickle ~16× to roughly 10 MB. Pickle load drops from ~10 s to <1 s, well below user-noticeable.

> **What Phase 2 does NOT touch**: detail drill-down (clicking into a number to see the underlying journal entries) still needs row-level data. That path keeps calling `fetch_pnl_data` and `fetch_pnl_only`. Only the *summary* path moves to the fact table. The BS path is also out of scope — Phase 2 ships a P&L fast path only.

**User experience after Phase 2**: a cold-worker first click on any company drops from ~10 s to <1 s. Subsequent clicks on the same worker stay sub-second as today. The footer gains a "data as of YYYY-MM-DD 02:00 PE" indicator so users know summary numbers are nightly. Drill-down latency is unchanged and continues to hit the live view.

## DBA decision

The fact table lives on a SQL Server we don't own. Two paths; we decide in the kickoff meeting based on what the DBA agrees to.

### Questions to ask the DBA

1. Can you expose the **underlying tables** behind `REPORTES.VISTA_ANALISIS_CECOS` so a SQL Agent job in your shop can `INSERT ... SELECT` from them into a new fact table?
2. If not, can you give us **read access to the view** plus permission to write the fact table into a database **we own**, and we run the ETL on our side?
3. What is your SLA for adding a new SQL Agent job? (We need the table rebuilt nightly at 02:00 PE.)
4. Will the closing-entries filter (`FUENTE NOT LIKE 'CIERRE%'`, applied today in [backend/data/queries.py:57](../backend/data/queries.py#L57)) be applied at fact-table build time, or do we apply it post-fetch on our side?
5. Can you index the fact table with a clustered index on `(CIA, ANIO, MES, CUENTA_CONTABLE)`?
6. Where does the FECHA_ACT timestamp live in the source tables, so we can surface `MAX(FECHA_ACT)` as a "data as of" indicator?

### Path A — DBA-owned (preferred)

DBA builds `REPORTES.FACT_ANALISIS_MENSUAL` via a SQL Agent job running nightly at 02:00 PE against the underlying tables behind `VISTA_ANALISIS_CECOS`. We get read access and nothing else changes on their side.

| Pros | Cons |
|------|------|
| Single source of truth; no second database to operate | Schedule + index choices outside our control |
| No new infra on our box | DBA timeline is the long pole |
| `FECHA_ACT` derivable from source tables natively | Question 1 above is the gating answer |

### Path B — Ours (fallback)

We build the fact table in a database we own (a new SQLite file at `backend/data/fact_table.db`, or a dedicated MSSQL instance if available), populated nightly by a Python ETL job that reads `VISTA_ANALISIS_CECOS` once at 02:00 PE and writes the aggregate. The ETL is a new daemon thread or systemd timer modeled after [backend/services/refresh_scheduler.py](../backend/services/refresh_scheduler.py).

| Pros | Cons |
|------|------|
| Unblocks us if DBA cannot expose underlying tables | Two databases to keep in sync conceptually |
| Schedule + schema entirely in our control | The nightly ETL still hits `VISTA_ANALISIS_CECOS` — slower than DBA-side, but only at 02:00 PE |
| FECHA_ACT recorded by us at write time | New file in our deploy: ETL script + table DDL + systemd timer (or thread) |

### Decision criteria

- Choose **Path A** if the DBA answers "yes" to question 1 or 2(a) (exposing tables) within the kickoff meeting.
- Choose **Path B** if the DBA says "view only" or "we cannot add SQL Agent jobs in <2 weeks." Path B is the escape hatch; the rest of this doc is written so the code paths under both options are nearly identical, differing only in the connection string and DDL location.

## Architecture

### Fact table schema

```
REPORTES.FACT_ANALISIS_MENSUAL  (or  flx.FACT_ANALISIS_MENSUAL  under Path B)

  CIA               VARCHAR / NVARCHAR    -- 'FIBERLINE' | 'FIBERLUX' | 'FIBERTECH' | 'NEXTNET'
  ANIO              SMALLINT
  MES               TINYINT               -- 1..12
  CUENTA_CONTABLE   VARCHAR / NVARCHAR
  CENTRO_COSTO      VARCHAR / NVARCHAR
  DEBITO            DECIMAL(18, 2)        -- SUM(DEBITO_LOCAL)  with FUENTE NOT LIKE 'CIERRE%'
  CREDITO           DECIMAL(18, 2)        -- SUM(CREDITO_LOCAL) with FUENTE NOT LIKE 'CIERRE%'
  FECHA_ACT         DATETIME              -- MIN(FECHA_ACT) of source rows in the bucket

  Clustered index: (CIA, ANIO, MES, CUENTA_CONTABLE)
  Rebuilt nightly at 02:00 PE.
```

Grain: one row per `(CIA, ANIO, MES, CUENTA_CONTABLE, CENTRO_COSTO)`. Real companies only; **CONSOLIDADO is not stored** in the fact table — it is built at fetch time by concatenating the 4 real-company fast fetches in Python. This is bit-identical with the existing path's behaviour, where [_fetch_consolidated](../backend/data/fetcher.py#L191) already runs 4 single-company queries in parallel and `pd.concat`s the results (line 207). The handoff prompt's empirical commutativity proof (2026-05-14, this session) extends to the aggregated case because `prepare_stmt` and `pl_summary` commute with `pd.concat`.

> **Why not pre-derive `PARTIDA_PL` and `IS_INTERCOMPANY` into the fact table columns?** Because [assign_partida_pl](../backend/services/accounting/transforms.py#L97) and the `IS_INTERCOMPANY` derivation at [transforms.py:152-154](../backend/services/accounting/transforms.py#L152) are SACRED. Materializing them in SQL forks the definition. Keep the columns at their raw grain (`CUENTA_CONTABLE`, `CENTRO_COSTO`) and let the Python layer derive both from them — the small aggregated DataFrame is still 10 MB, the derivation is microseconds.

### New fast-path queries

| Function | Lives in | Replaces (when flag is on) | Returns |
|----------|----------|---------------------------|---------|
| `fetch_pnl_summary_fast(conn, company, year)` | `backend/data/queries.py` (new, alongside `fetch_pnl_data`) | The per-company arm of [fetch_pnl_only](../backend/data/fetcher.py#L169) (which today calls `fetch_pnl_data`). | Aggregated DataFrame at fact-table grain |
| `fetch_pnl_consolidated_fast(year, conn_factory)` | `backend/data/fetcher.py` (new, alongside `fetch_pnl_consolidated`) | [fetch_pnl_consolidated](../backend/data/fetcher.py#L212), which today fans out 4 row-level queries. | `pd.concat` of 4 fast-fetch results |

Both functions return a DataFrame with **the same columns the current row-level fetch returns** (`CIA, CUENTA_CONTABLE, DESCRIPCION, NIT, RAZON_SOCIAL, CENTRO_COSTO, DESC_CECO, FECHA, DEBITO_LOCAL, CREDITO_LOCAL, ASIENTO`), but with **far fewer rows** (one per `(MES, CUENTA, CECO)` instead of one per journal entry). The non-grain columns are filled as follows:

- `DESCRIPCION`, `DESC_CECO`: lookup against a small descriptions cache (today these come straight from the view; under the fact table we need to populate them post-fetch from the same source). If the lookup is non-trivial, the simpler option is to add `DESCRIPCION` and `DESC_CECO` as additional grain-adjacent columns in the fact table, accepting the cardinality bump (one description per cuenta-ceco pair is finite). **Decide in kickoff.**
- `NIT`, `RAZON_SOCIAL`: not present in the summary path; set to empty strings. The summary pipeline does not read them. Drill-down hits the row-level path which still has them.
- `FECHA`: synthesize as `date(year, mes, 1)` — the summary path only uses month, not exact date.
- `ASIENTO`: not used downstream of `prepare_stmt` for summary. Set to empty.

The downstream pipeline (`_run_pl_summary_only` → `prepare_stmt` → `pl_summary`) sees a DataFrame of the same shape and runs unchanged.

### Per-company feature flag

Five environment variables, default false. Pattern mirrors `STRICT_BS_BALANCE` at [backend/config/settings.py:60](../backend/config/settings.py#L60):

```
USE_FACT_TABLE_FIBERLUX=true
USE_FACT_TABLE_FIBERTECH=true
USE_FACT_TABLE_FIBERLINE=true
USE_FACT_TABLE_NEXTNET=true
USE_FACT_TABLE_CONSOLIDADO=true
```

CONSOLIDADO's flag is **logically gated** on all 4 real companies' flags being on too, since CONSOLIDADO is built from them. The dispatch helper enforces this; the diff harness verifies it.

## Implementation

File-by-file. Lines refer to the staging tree at the time this doc was written (2026-05-14); verify with `sed -n '<line>p' <file>` before editing.

### New file: nothing in `backend/data/queries.py` itself yet — just an addition

Add `fetch_pnl_summary_fast(conn, company, year)` after [fetch_pnl_data](../backend/data/queries.py#L79). Skeleton:

```python
def fetch_pnl_summary_fast(conn, company: str, year: int) -> pd.DataFrame:
    """Fast P&L summary fetch from REPORTES.FACT_ANALISIS_MENSUAL.

    Returns rows at (CIA, ANIO, MES, CUENTA, CECO) grain, shaped to match
    the existing fetch_pnl_data column set so downstream transforms are
    unchanged.  Used only on the summary path; drill-down keeps using
    fetch_pnl_data.
    """
    # SELECT ... FROM REPORTES.FACT_ANALISIS_MENSUAL WHERE CIA = ? AND ANIO = ?
    # Then post-process: add DESCRIPCION/DESC_CECO via the joined columns
    # (Path A: in the fact table; Path B: looked up from a cached map),
    # synthesize FECHA = date(year, MES, 1), fill NIT/RAZON_SOCIAL/ASIENTO=''.
    ...
```

The exact SQL depends on Path A vs Path B (different schema/database). Both return the same DataFrame.

### Edit: `backend/data/fetcher.py`

Add `fetch_pnl_consolidated_fast(year, conn_factory=None)` alongside [fetch_pnl_consolidated](../backend/data/fetcher.py#L212). Implementation: same shape as [_fetch_consolidated](../backend/data/fetcher.py#L191), substituting `fetch_pnl_summary_fast` for `fetch_pnl_data`. No new SQL — just a different per-company fetch function fed into the same ThreadPoolExecutor + `pd.concat` pattern.

### Edit: `backend/config/settings.py`

Extend `Config` dataclass at [settings.py:38-43](../backend/config/settings.py#L38) with one boolean per company (5 fields), and parse them in `get_config()` at [settings.py:57](../backend/config/settings.py#L57). Pattern follows `strict_bs_balance` at line 60. Add a helper:

```python
def use_fact_table_for(self, company: str) -> bool:
    """True iff the per-company flag is set for this company."""
    ...
```

The helper lives on `Config` so `_ensure_pl_stmt_cached` reads it with one call.

### Edit: `backend/services/data_service.py`

The intercept lives at lines 841-843 of [_ensure_pl_stmt_cached](../backend/services/data_service.py#L793). Today:

```python
raw = (fetch_pnl_consolidated(year)
       if company == CONSOLIDADO
       else fetch_pnl_only(company, year))
```

Becomes:

```python
if get_config().use_fact_table_for(company):
    raw = (fetch_pnl_consolidated_fast(year)
           if company == CONSOLIDADO
           else _fetch_with_own_conn(fetch_pnl_summary_fast, connect, company, year))
    logger.info("P&L fetch (fast path): %.2fs (%d rows)", time.perf_counter() - t0, len(raw))
else:
    raw = (fetch_pnl_consolidated(year)
           if company == CONSOLIDADO
           else fetch_pnl_only(company, year))
    logger.info("P&L fetch: %.2fs (%d rows)", time.perf_counter() - t0, len(raw))
```

Everything downstream of this — `_run_pl_summary_only(raw)` at line 846, the four `_caches[...].set(...)` calls at 850-855, and the four [_save_to_disk](../backend/services/data_service.py#L264) calls at 859-862 — runs unchanged. The pickles on disk become smaller (the new fast path's `raw` is ~10 MB vs. the row-level path's ~250 MB for CONSOLIDADO), which is exactly the point.

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

### Frontend: "data as of" footer

The dashboard currently shows no last-refresh timestamp (verified by searching `frontend/src/` for "data as of", "last updated", "refreshed", "timestamp" — no hits). Add a small pill in [frontend/src/features/dashboard/TopBar.tsx](../frontend/src/features/dashboard/TopBar.tsx) (or in the existing main dashboard frame, designer's call) that displays a `data_as_of` value returned from the API. The value comes from the fact table's `MAX(FECHA_ACT)` per `(company, year)` and is propagated through `load_pl_data`'s return dict.

Ship the footer with the FIBERTECH flag flip, not the FIBERLUX one — that way one company's worth of soak has confirmed the fast path before users see "yesterday's data" as a visible UX promise.

## Validation

### Diff harness must show zero diffs

For every `(company, year, month)` triple across `{FIBERLINE, FIBERLUX, FIBERTECH, NEXTNET, CONSOLIDADO} × {2025, 2026} × {1..12}`, the diff harness runs both code paths and compares output at the `(PARTIDA_PL, month)` grain for three pivots: `pl_summary`, `pl_summary_ex_ic`, `pl_summary_only_ic`.

> **What counts as "bit-identical"**: zero non-zero rows in the elementwise diff at the `(PARTIDA_PL, month)` grain for all three pivots. We compare *summed measures*, not raw row counts — row counts will not match because the fact table is aggregated. If a diff is non-zero, fix the fact table SQL (typically a missed `FUENTE NOT LIKE 'CIERRE%'` filter or a sign-convention drift on a specific account), not the harness threshold.

### Per-company rollback

If a regression surfaces after a per-company flag flip on prod, set the corresponding `USE_FACT_TABLE_<COMPANY>=false` in `.env`, restart the service (`sudo systemctl restart flxcontabilidad`), validate that the dashboard re-serves correct numbers from the row-level path, file an issue for the underlying SQL fix. Other companies' flags stay on. The disk pickle cache should be invalidated on rollback so subsequent fetches re-populate from the live view; verify [invalidate_cache](../backend/services/data_service.py#L223) clears both `df_stmt_*` and the new `fact_*` pickles before shipping.

## Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| **SACRED drift via the fact table SQL.** Server-side `SUM` may differ from pandas `sum`: NULL handling, decimal rounding, CIERRE filter applied at the wrong stage. | Medium pre-validation, zero after diff harness passes | High | Diff harness must be zero for every triple. No exceptions. If diffs are non-zero, fix the SQL, never the threshold. |
| **Fact table staleness**: rebuilt nightly at 02:00 PE; mid-day journal entries don't appear in summary view until the next rebuild. | Certain (it's the design) | Medium | Footer "data as of YYYY-MM-DD 02:00 PE". Detail drill-down still hits the live view. Finance team confirmation before CONSOLIDADO flips. |
| **DBA timeline outside our control.** | Medium | Medium | Path B is the escape valve; decide in kickoff. |
| **`IS_INTERCOMPANY` derivation drift** if the fact table omits CUENTA or CECO from the grain. | Very low (grain explicitly includes both) | High | Schema review in kickoff. Diff harness catches it regardless. |
| **Flag-flip inconsistency across workers** if `.env` is reloaded mid-flight. | Low | Medium | Env vars are read at boot only. Restart is the contract; document in DEPLOYMENT.md. |
| **CIERRE-filter parity broken** in fact table. | Medium pre-validation | High | Diff harness catches it; verify with DBA at kickoff. Today the filter lives at [queries.py:57](../backend/data/queries.py#L57); the fact table must replicate it. |
| **Disk-pickle staleness on flip-back.** If we flip a company off, the `fact_*.pkl` is no longer the authoritative cached representation; the row-level path doesn't read it. | Low | Low | `invalidate_cache(company, year)` already clears the per-`(company, year)` slot in every cache bucket. Add a check that the `fact` kind is included in `_delete_disk_cache` before shipping. |
| **Descriptions cardinality** if we add `DESCRIPCION` and `DESC_CECO` to the fact table grain. | Low | Low | Description per `(cuenta, ceco)` pair is bounded; rough estimate ~50K rows per company-year, still 10× smaller than today's row-level pickle. |

## Rollout

In order, with go/no-go gates between steps.

1. **DBA kickoff** (~1 day). Send the schema + the six questions above. Decide Path A vs Path B at the end of the meeting. If Path B, scope our ETL job in the same meeting.
2. **SQL artifact built** (~3-5 days, external). Blocks us. Path A: DBA's SQL Agent job lands and we validate one row by hand. Path B: we write `backend/scripts/build_fact_table.py` plus a systemd timer modeled after [refresh_scheduler.py](../backend/services/refresh_scheduler.py), and run it nightly on the prod box.
3. **Fast-path code + flag + diff harness on `dev`** (~2 days). New `fetch_pnl_summary_fast`, `fetch_pnl_consolidated_fast`, settings flags, intercept in `_ensure_pl_stmt_cached`, new `backend/scripts/diff_fact_vs_view.py`. Commit message: `feat(fact-table): fast-path P&L summary fetch behind per-company flags`.
4. **Diff harness validates zero diffs across all triples** (~1 day). Run on staging with all 5 flags toggled on in-process by the harness. Zero diffs is the gate. If any diff is non-zero, return to step 2 — fix the SQL.
5. **Per-company flip + 48 h soak on staging**, in order:
   - FIBERLUX (smallest, lowest blast radius)
   - FIBERTECH
   - FIBERLINE
   - NEXTNET
   - CONSOLIDADO last (depends on the 4 real-company flags being stable)
6. **Footer "data as of"** ships alongside the FIBERTECH flip after FIBERLUX soaks cleanly.
7. **Promote to prod** via `./promote.sh` from the prod tree per [DEPLOYMENT.md](DEPLOYMENT.md). Same flag flips repeated on prod, 48 h soak per company. Promotion of the flag is a `.env` edit on prod plus `sudo systemctl restart flxcontabilidad`.

> **Do not flip CONSOLIDADO first to "see the biggest win."** CONSOLIDADO is `pd.concat` of 4 real-company fast fetches; if the fact table has a bug for one company, you will spot it faster on a single-company rollout.

## Effort and timeline

Split between our team and the DBA.

| Item                                       | Days | Owner |
|--------------------------------------------|------|-------|
| DBA kickoff spec + meeting                 | 1.0  | Ours  |
| Fact table DDL + nightly job               | 3–5  | DBA (blocks us). Path B reduces to ~2 days ours. |
| `fetch_pnl_summary_fast` + flag wiring + intercept in `_ensure_pl_stmt_cached` | 2.0  | Ours  |
| Diff harness + cross-company validation    | 1.0  | Ours  |
| Per-company rollout + 48 h soak each       | ~10 days elapsed (~2 days active) | Ours |
| Footer "data as of"                        | 0.5  | Ours  |
| **Ours, active**                           | **~5 days** | |
| **Elapsed, dominated by DBA + soak**       | **~2 weeks** | |

## What this doc is not

This doc is not a BS fast path. Phase 2's scope is P&L summary only; a BS equivalent could follow if the same pickle-load problem materializes there, but Phase 2 ships P&L alone.

This doc is not a replacement for [SCHEDULED_REFRESH.md](SCHEDULED_REFRESH.md). The scheduler still fires hourly; the fact table just makes each fetch + serialize cycle dramatically cheaper. Both layers stay.

This doc is not a Redis reintroduction. If finance flags the nightly staleness window as too coarse for summary use, Phase 1 (Redis-backed cache from [SCALING_ROADMAP.md](SCALING_ROADMAP.md)) stays available as the next architectural unlock. Phase 2 is orthogonal to it.
