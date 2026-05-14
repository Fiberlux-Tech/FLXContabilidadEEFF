# Scaling Roadmap

> **Status**: Phase 0 partially shipped 2026-05-12 (3 commits on `dev`); Phase 1 and Phase 3 **deferred** in favor of hourly scheduled refresh (see "Scope change" below and [SCHEDULED_REFRESH.md](SCHEDULED_REFRESH.md)).
> **Owner**: Backend team.
> **Last updated**: 2026-05-12 (scope change).
> **Supersedes**: Tier 2 and Tier 3 of [CONCURRENCY_SCALING.md](CONCURRENCY_SCALING.md). That doc's Tier 1 (timeout bump, single-flight, warmup post-mortem) remains the historical record for the 2026-05-05 incident and the 2026-05-12 warmup revert; do not re-litigate those sections here.

## Why this document exists

[CONCURRENCY_SCALING.md](CONCURRENCY_SCALING.md) was written reactively after a single `HYT00` timeout. Tier 1 shipped and removed that failure mode. Tier 1.2 (startup warmup) was implemented on 2026-05-12, OOM-killed prod twice the same day, and was reverted.

That revert exposed the constraint this doc is built around: **the prod host is 5.8 GB RAM + 3.8 GB swap and cannot be expanded.** Everything below is framed around fitting the Fiberlux finance team (~10–25 concurrent users) into that fixed envelope without crashes.

This is capacity planning, not outage response.

---

## Memory budget

The 5.8 GB ceiling is non-negotiable. Every phase must justify itself against this table.

| Consumer                                    | Today (post Tier 1) | After Phase 0 | After Phase 1 | After Phase 2 | After Phase 3 |
|---------------------------------------------|---------------------|---------------|---------------|---------------|---------------|
| OS + nginx + sqlite + agents                | ~1.0 GB             | ~1.0 GB       | ~1.0 GB       | ~1.0 GB       | ~1.0 GB       |
| 3 gunicorn workers (peak resident)          | 3 × 1.0–1.5 GB      | 3 × ~0.7 GB   | 3 × ~0.3 GB   | 3 × ~0.3 GB   | 3 × ~0.4 GB   |
| Redis (`maxmemory 2gb`)                     | —                   | —             | up to 2.0 GB  | up to 1.5 GB  | up to 1.5 GB  |
| Headroom / page cache                       | ~0.3 GB observed    | ~1.5 GB       | ~1.5 GB       | ~2.0 GB       | ~1.5 GB       |
| Peak observed at last OOM (2026-05-12)      | 5.2 GB              | n/a           | n/a           | n/a           | n/a           |

Worker RSS figures are observed during the warmup OOM and the post-revert steady state; treat the post-phase numbers as targets, not measurements. Verify with the Phase 0 memory log before declaring a phase complete.

> **The constraint that drives the whole plan**: today, each worker independently caches the same DataFrames. With 3 workers and CONSOLIDADO_2025's `df_stmt` at ~600 MB in memory, three users hitting three workers can pull the same 1.8 GB into RAM simultaneously. Phase 1 exists to break that multiplication.

---

## What "solved" looks like

| Scenario                                                 | Today (Tier 1) | After Phase 0 | After Phase 1 | After Phase 2 | After Phase 3 |
|----------------------------------------------------------|----------------|---------------|---------------|---------------|---------------|
| First user after deploy, cold cache, opens FIBERLINE     | works, 30–60 s | works, 30–60 s | works, 30–60 s | works, 5–15 s | works, 5–15 s |
| 5 concurrent users, same company, same year              | works, may swap | works         | works         | works         | works         |
| 5 concurrent users, 5 different companies                | OOM risk      | survives, slow | works         | works         | works         |
| 20 concurrent users, browsing (mostly cache hits)        | OOM likely    | OOM possible  | works         | works         | works         |
| 25 concurrent users actively drilling into detail        | OOM           | OOM           | works, slow   | works         | works         |
| 30+ concurrent users                                     | OOM           | OOM           | OOM possible  | works         | works         |

Targets, not benchmarks. Each phase's validation section defines how to confirm its row.

---

## Hard limits we accept

- The box is **5.8 GB RAM + 3.8 GB swap**, confirmed by the user 2026-05-12; not expandable in this fiscal window.
- Swap is effectively useless under interactive load — observed exhaustion during the warmup OOM. Treat the working set as if swap doesn't exist.
- Past Phase 3, the realistic ceiling on this hardware is roughly **25–30 concurrent active users** (verify by load test before promising more). Beyond that, only more RAM helps; no software change in this plan removes that wall.
- The SQL Server view `REPORTES.VISTA_ANALISIS_CECOS` (~8.4 M rows) is owned by the DBA team and is **live** (changes posted by finance appear immediately). Phase 4 requires DBA cooperation. Phase 2 does **not** — it builds local fact pickles from data we already fetch hourly via the scheduler.
- The accounting transformation pipeline ([CODING_PATTERNS.md](CODING_PATTERNS.md) "Accounting Logic — SACRED, DO NOT MODIFY") is fixed. Any phase that touches data flowing into it must produce bit-identical numbers.

---

## Scope change 2026-05-12: scheduled refresh supersedes Phase 1

After weighing the architectural cost of introducing Redis against the user's stated tolerance for **up to one hour of data staleness**, we pivoted away from a shared in-memory cache and toward an **hourly scheduler that refreshes the disk pickle cache for all 5 companies × 2 years between 7am and 9pm Lima time, every day including weekends**. User requests are then served exclusively from the warmed disk/in-memory caches; no user request ever triggers a DB fetch on the summary path. Full design in [SCHEDULED_REFRESH.md](SCHEDULED_REFRESH.md).

What this changes for the roadmap:

| Phase | Previous status | New status |
|-------|-----------------|------------|
| Phase 0 — Safety nets                  | In flight | **Still required**, work continues unchanged. The cgroup ceiling, smaller LRU caps, `FETCH_MAX_WORKERS=2`, and `mem_monitor` are belt-and-suspenders for the scheduler's working memory. |
| Phase 1 — Redis-backed cache           | Next      | **De-phased.** The scheduler removes the duplicate-fetch problem Phase 1 was designed to solve, and Phase 2 makes the cache duplication economically irrelevant. Phase 1 only buys *sub-hour freshness* over the current design, which finance has not requested. Spec retained as audit trail and contingency. Do not implement unless (a) Phase 2 has shipped and (b) finance explicitly asks for sub-hour data freshness. |
| Phase 2 — Monthly fact table           | Queued    | **Still relevant.** Shrinks the DataFrames the scheduler has to hold, helping the 5.8 GB envelope. |
| Phase 3 — gthread workers              | Queued    | **Deferred.** Concurrency contention on the summary path stops being a bottleneck once the cache is always warm. Revisit only if drill-down (which still hits row-level data) becomes a queue-depth problem. |
| Phase 4 — DBA index work               | Parallel  | **Unchanged.** Helps both scheduler-driven fetches and detail drill-down. |

Phase 0 work remaining on `dev` (not yet deployed): the `MemoryHigh=4G` / `MemoryMax=5G` systemd edit and the `FETCH_MAX_WORKERS=2` `.env` edit on staging+prod. Those ship as planned. The three Phase 0 commits already on `dev` (`c36d557`, `807d539`, `f17ea04`) stay; they are still useful safety nets even with the scheduler.

The deferred phase sections below remain as the canonical specs for any future revival; they are no longer the active plan.

---

## Operational guardrails

The "never again" list from the 2026-05-12 post-mortem. These apply to every phase below.

1. **Never eagerly load all companies at boot.** Warmup is banned on this hardware; rely on the natural cache fill driven by user requests. Re-read the warmup post-mortem in [CONCURRENCY_SCALING.md](CONCURRENCY_SCALING.md) section 1.2 before proposing anything that walks `COMPANIES` in a loop.
2. **Never multiply the working set by the number of workers.** Any cache that lives in a worker process is paid for N times. If a cache entry is large (df_stmt, raw), it belongs in Redis (Phase 1) or in a smaller representation (Phase 2), not in the worker.
3. **Always check the memory budget before adding cache entries.** The 12 buckets in `_caches` at [backend/services/data_service.py:187](../backend/services/data_service.py#L187) collectively hold ~12 × `max_entries` × per-entry-size bytes per worker. Adding a 13th bucket or raising `max_entries` requires a written memory calculation.
4. **Single-flight stays.** The locks in [data_service.py](../backend/services/data_service.py) (`_get_inflight_lock` + `_CrossProcLock`) are load-bearing. Phase 1 replaces the flock with a Redis `SET NX EX` but does not remove the contract.
5. **No deploy on Friday afternoon Lima time.** If a memory regression slips through staging, the OOM cycle will run unattended over the weekend.

---

## Phase 0 — Safety nets

> **Goal**: Make the box fail safely while everything else is still in flight. No architectural commitments; everything here is reversible in minutes.

**Why**: The 2026-05-12 OOM had no early warning — gunicorn went from healthy to killed in seconds because the kernel OOM-killer picks its victim arbitrarily and we had no upstream memory pressure mechanism. We need (a) a cgroup ceiling so systemd, not the kernel, decides what dies, (b) smaller in-memory caches so a single bad request can't push a worker past the cliff, and (c) a paper trail so we know which scenario triggered the next near-miss.

### What changes

1. **Add memory limits to the systemd unit** (`/etc/systemd/system/flxcontabilidad.service`, currently no `MemoryMax`/`MemoryHigh`; staging unit is `flxcontabilidad-staging.service`):
   ```ini
   [Service]
   MemoryHigh=4G
   MemoryMax=5G
   ```
   `MemoryHigh` triggers cgroup-level throttling and aggressive reclaim before processes die; `MemoryMax` is the hard kill ceiling for the cgroup. Reload with `sudo systemctl daemon-reload && sudo systemctl restart flxcontabilidad`.

2. **Shrink heavy cache buckets** at [backend/services/data_service.py:187](../backend/services/data_service.py#L187). The constructor default is `max_entries=20` ([data_service.py:60](../backend/services/data_service.py#L60)). Override per-bucket:
   - `pl_stmt`, `df`, `bs`, `raw` → `max_entries=6` (these hold full DataFrames)
   - Leave `pl_preagg`, `pl_preagg_ex_ic`, `pl_preagg_only_ic`, `pl_sections`, `pl_df`, `pl_result`, `bs_result`, `result` at the default (these are small or already aggregated)

   With 5 companies × 2 years = 10 cells, 6 entries per bucket means the LRU evicts companies a worker hasn't touched in 30 min. The pre-fetch chain (`_prefetch_bs_background`, `_prefetch_prev_year_background`, `_prefetch_pl_sections_background`) keeps the most-recently-used pair hot.

3. **Drop `FETCH_MAX_WORKERS` from 5 to 2** in `.env` (default at [backend/config/settings.py:33](../backend/config/settings.py#L33), env override at [settings.py:70](../backend/config/settings.py#L70)). Original Tier 2.3 framed this as DB-contention; reframe: fewer concurrent fetches means less concurrent pandas allocation per request, which is what's actually pressuring memory under load. The DB-contention argument still holds but is secondary.

4. **Periodic memory log line.** New module `backend/services/mem_monitor.py` (~30 lines): a daemon thread started from `backend/app.py` factory that logs `psutil.virtual_memory()` (`total`, `available`, `percent`) plus the current process RSS to `backend/logs/error.log` every 300 s. No Prometheus, no Grafana yet — just a grep-able trail.

### Effort

| Item             | Hours |
|------------------|-------|
| systemd edit     | 0.5 (implementation) + 0.5 (validation) |
| Cache size tune  | 0.5 (implementation) + 1.0 (validation under realistic browsing) |
| `.env` knob      | 0.25 + 0.5 |
| mem_monitor.py   | 1.5 + 0.5 |
| Staging soak     | 2.0 (just leave it running and tail logs) |
| **Total**        | **~1 working day** |

### Risks

- **`MemoryMax=5G` could kill gunicorn under a legitimate spike before Phase 1 ships.** Mitigation: `MemoryHigh=4G` gives the cgroup a soft warning; if the access log shows OOM-from-cgroup events, raise `MemoryMax` to 5.4 GB temporarily.
- **Smaller LRUs could increase cache-miss rate for users hopping companies.** Mitigation: the disk cache at `backend/services/.stmt_cache/` (verified 2026-05-12: 257 MB for CONSOLIDADO_2025 down to 2.1 MB for FIBERLUX_2026) absorbs evictions cheaply — `_try_pl_stmt_from_disk` re-hydrates a worker in seconds, not minutes.
- **`FETCH_MAX_WORKERS=2` slows `fetch_pnl_consolidated`.** Consolidated fetches 4 companies in parallel ([backend/data/fetcher.py:191](../backend/data/fetcher.py#L191)); with 2 workers they serialize 2-by-2. Acceptable: CONSOLIDADO is the single biggest memory risk, slower-and-survives beats faster-and-OOMs.
- **No interaction with SACRED rules.** This phase changes no SQL, no aggregation, no transform. Safe to ship without an accounting review.

### Validation criteria

- After 24 h on staging, `grep "mem_monitor" backend/logs/error.log` shows `available` never dropping below 800 MB during normal browsing.
- `systemctl status flxcontabilidad-staging` shows `Memory: <5G` consistently; no `Killed: signal=9` lines in `journalctl -u flxcontabilidad-staging`.
- Load test: 5 concurrent users each opening a different company, repeated 3 times → no OOM, no 500s, p95 latency on the second pass < 5 s (verify before shipping; we have no recorded baseline).

### Hard prerequisites

None. Phase 0 starts immediately.

### What NOT to do

- Do **not** raise `max_entries` on heavy buckets to "be safe". The whole point is to bound worker RSS.
- Do **not** reintroduce a warmup hook ("just for FIBERLUX, it's tiny") — same revert applies. The natural cache fill is the contract.
- Do **not** add `MemoryMax` to the gunicorn worker process directly via `--limit-as` or similar; cgroup-level limits are what we want, per-process limits will kill mid-pandas-allocation and corrupt the disk cache mid-pickle.

---

## Phase 1 — Move state out of workers (Redis-backed cache) (DEFERRED 2026-05-12)

> **Status**: De-phased. Not worth implementing under the current constraints. Kept in this document as an audit trail of the design decision and as a contingency spec if the constraints change.
>
> **Why this is no longer the right move**: Phase 1 was written to solve two problems at once — (a) cross-worker cache duplication and (b) slow cold cache reads. The scheduled-refresh design + Phase 2 (fact table) together address the user-visible symptoms of both:
> - The **scheduler** (shipped 2026-05-12) removes all DB queries from the user request path. The "duplicate fetch" problem Phase 1 was the canonical answer to no longer exists, because no user request fetches anything; the scheduler does, in a single elected worker.
> - **Phase 2** shrinks each cached DataFrame from ~150 MB pickled to ~10 MB. Once pickle loads are sub-second, the fact that each worker keeps its own copy stops being economically interesting — 3 × 10 MB × 10 entries = ~300 MB across all workers, well inside the 5.8 GB budget. The cross-worker duplication that Phase 1 was designed to eliminate becomes a footnote, not a bottleneck.
>
> **What Phase 1 would still uniquely solve**: real-time freshness. The scheduler caps freshness at one hour by design; the user accepted that on 2026-05-12. If finance ever needs sub-minute freshness — for example, if a workflow emerges where users post a journal entry and immediately refresh to confirm it appeared — Phase 1 is the way to deliver that. The scheduler can't, because it's structurally hourly. Redis-backed caching with on-request fills is the answer if and only if that requirement appears.
>
> **Do not implement Phase 1 unless**: (a) Phase 2 has shipped and is stable, and (b) finance has explicitly asked for sub-hour data freshness. Without both, Phase 1's complexity (new dependency, new failure mode, new ops surface) buys nothing the current design doesn't already deliver.
>
> **Goal (if revived)**: Take the DataFrames out of gunicorn process memory entirely, so worker RSS is dominated by code + per-request scratch, not by accumulated cache state.

**Why (original framing, pre-pivot)**: Today, 3 workers × peak ~1.5 GB resident is the structural ceiling, and most of that 1.5 GB is cached DataFrames duplicated across workers. Moving the cache into a single Redis process with `maxmemory 2gb maxmemory-policy allkeys-lru` reclaims roughly 2 GB of duplicated state while bounding the cache itself with an eviction policy we control. Workers become almost stateless. As a free upgrade, cross-process single-flight (`_CrossProcLock`) collapses from a `fcntl.flock` dance into a one-liner `SET NX EX`.

### What changes

1. **New file `backend/services/cache_redis.py`** (~150 lines): a class `RedisLRUTTLCache` that exposes the same `get(company, year)`, `set(company, year, value)`, `pop(company, year)`, `clear()`, `stats()` surface as `LRUTTLCache` at [data_service.py:54](../backend/services/data_service.py#L54). Values are pickled (use `pickle.HIGHEST_PROTOCOL`; pandas pickles are already the disk format, so the cost is known: ~2–5 s round-trip for CONSOLIDADO_2025's 257 MB pickle — single-flight absorbs concurrent callers).
2. **Modify `backend/services/data_service.py:187`**: replace each `LRUTTLCache(...)` with `RedisLRUTTLCache(name=..., ttl=1800)`. Call sites do not change. Per-bucket size limits move from a Python `max_entries` into Redis-level `maxmemory` enforcement on the namespace.
3. **Fallback path**: every Redis call inside `RedisLRUTTLCache` is wrapped in `try / except (redis.ConnectionError, redis.TimeoutError)`. On failure, `get` returns `None` (treat as miss) and `set` logs + no-ops. The disk cache at `backend/services/.stmt_cache/` remains and becomes the durable fallback — when Redis is down, the system degrades to "first user pays the fetch, subsequent users hit the disk cache, no shared in-memory layer." Not great, not broken.
4. **Replace `_CrossProcLock`** with `_RedisSingleFlight`: `SET flx_inflight_<kind>_<company>_<year> <worker_id> NX EX 300`. The fcntl-based flock and the `/tmp/flx_inflight_*` lock files go away. Keep `_get_inflight_lock` (the in-process `threading.Lock` dict) — it's still needed once Phase 3 introduces threaded workers.
5. **Infrastructure**:
   - Add `redis>=5.0` to `requirements.txt`.
   - Install Redis via `apt install redis-server` (Ubuntu 22.04 ships 6.0.16, which is fine; verify before shipping).
   - New systemd dropin `/etc/systemd/system/redis-server.service.d/flx.conf` with `MemoryMax=2G` so Redis can never blow past its share of the budget.
   - `/etc/redis/redis.conf`: `maxmemory 2gb`, `maxmemory-policy allkeys-lru`, `save ""` (we don't need persistence; the disk cache is our durable layer), `bind 127.0.0.1`.
   - Update `setup_infrastructure.sh` to install/enable redis on fresh boxes.
6. **No service unit change** required for FLX itself — Redis runs as its own unit. The FLX `.env` gains `REDIS_URL=redis://127.0.0.1:6379/0`.

### Effort

| Item                              | Days |
|-----------------------------------|------|
| `cache_redis.py` + tests          | 1.5 (implementation) |
| Replace cache wiring + flock      | 0.5 |
| Redis install + systemd dropin    | 0.5 (ops) |
| Fallback path manual test         | 0.5 (validation) |
| Soak under simulated load         | 1.0 (validation) |
| Staging burn-in                   | 1.0 (validation) |
| Promote + monitor                 | 0.5 (ops) |
| **Total**                         | **~5 working days (1 week)** |

### Risks

- **Pickle serialization cost is now on every cache hit, not just disk miss.** For CONSOLIDADO_2025 at 257 MB, a Redis hit means ~2–5 s of pickle work per worker per fetch (verify on staging with `timeit`). Mitigation: the value goes into the in-process `pl_df` / `pl_preagg` caches on hit, so the same worker pays once per TTL window, not per request. Net effect on cache-hit p95 should still beat a cold DB fetch by an order of magnitude.
- **Redis is now a single point of failure.** Mitigation: the fallback path above. Add a synthetic check ("can I `PING` Redis?") to the existing health endpoint so the load balancer / monitoring catches a dead Redis even if requests still succeed.
- **`SET NX EX 300` could leak a lock if a worker dies mid-fetch.** Mitigation: 300 s TTL matches `DB_QUERY_TIMEOUT`, so worst case other workers wait 5 min then retry. Acceptable. Do **not** set a longer TTL just because pickle is slow.
- **No SACRED interaction.** Phase 1 changes only the storage layer. No accounting code is touched. Still, run the staging diff (load FIBERLINE/2026, open every section, compare totals to prod) before promoting.
- **Deployment ordering matters.** The staging→prod workflow ([DEPLOYMENT.md](DEPLOYMENT.md)) requires Redis to be installed on prod *before* `./promote.sh` runs, or the new code will degrade to fallback on first boot. Ship Redis install as a manual ops step in the same maintenance window.

### Validation criteria

- Stop Redis (`sudo systemctl stop redis-server`). The app must still answer requests, with cache-miss log lines and degraded latency. No 500s.
- Restart Redis. Cache hits resume within one TTL window.
- With Redis up, restart gunicorn. The first request per `(company, year)` triggers a Redis cache fill from disk (since pre-Phase-1 disk caches still exist); the second request from a different worker is served from Redis with no DB hit. Verify via `redis-cli MONITOR` and `grep "P&L fetch" backend/logs/error.log` (should be silent on the second request).
- Worker RSS during steady-state browsing of 5 companies drops from ~1.0–1.5 GB to ~300 MB (verify on staging).
- Memory budget table row "After Phase 1" holds: workers ≤ 1 GB total, Redis ≤ 2 GB, headroom > 1 GB.

### Hard prerequisites

- Phase 0 must be complete and stable for at least 48 h. The `mem_monitor` log is how we'll know whether Phase 1 actually moved the needle vs. introduced a new regression.
- Redis package installed on the prod host (Ubuntu 22.04 confirmed; verify the apt repo before shipping).

### What NOT to do

- Do **not** put Redis behind nginx or expose it on the LAN — `bind 127.0.0.1` only. The data in Redis is not auth-scoped.
- Do **not** enable Redis persistence (`save` directives). The disk cache at `backend/services/.stmt_cache/` is our durable layer; Redis is a working-set cache, not a database.
- Do **not** raise `maxmemory` above 2 GB without redoing the memory budget table. Redis hitting 3 GB while workers also grow under load is exactly the scenario Phase 0 + Phase 1 are designed to prevent.
- Do **not** remove the disk cache "since we have Redis now." The disk cache is the fallback path *and* the bootstrap path after a deploy.

---

## Phase 2 — Shrink the working set (monthly fact pickles)

> **Goal**: Shrink the cached `df_stmt` DataFrames ~16× by aggregating to monthly grain. Cold-worker pickle load drops from ~10 s to <1 s, eliminating the user-visible tax left by the scheduler.
>
> **Status**: Implementation spec in [FACT_TABLE.md](FACT_TABLE.md). This section is the roadmap-level summary; do not duplicate detail here.

**Why**: `df_stmt_CONSOLIDADO_2025.pkl` is 257 MB on disk and ~600 MB in memory. The summary endpoints — the ones the dashboard hits on every page load — only need `(CIA, year, month, cuenta_contable, centro_costo, debito, credito)` sums. A pre-aggregated DataFrame at that grain is ~10 MB. Detail drill-down (clicking into a single number to see the underlying journal entries) keeps the row-level path unchanged.

**Design summary** (full spec in [FACT_TABLE.md](FACT_TABLE.md)):

1. **No DBA dependency.** The fact pickles are built on our box by extending the existing [refresh_scheduler.py](../backend/services/refresh_scheduler.py) cycle — after each `load_pl_data`, we `groupby + sum` the cached `df_stmt` and write `fact_{company}_{year}.pkl` to `backend/services/.stmt_cache/`.
2. **Same freshness as today.** Because the ETL piggybacks on the existing hourly scheduler, fact pickles refresh every hour during 7am–9pm Lima. Summary and drill-down share the same ~1 hour staleness window the system already has. **No "data as of yesterday" regression.**
3. **Per-company feature flag.** `USE_FACT_TABLE_<COMPANY>` env vars; flip one company at a time. Order: FIBERLUX → FIBERTECH → FIBERLINE → NEXTNET → CONSOLIDADO. CONSOLIDADO reads the 4 real-company pickles and concats — no separate ETL.
4. **Diff harness gate.** [backend/scripts/diff_fact_vs_view.py](../backend/scripts/diff_fact_vs_view.py) (new) must return zero diffs at the `(PARTIDA_PL, month)` grain for all triples before any flag flips.

> **Earlier revisions of this section proposed a DBA-owned nightly fact table on SQL Server.** That design was abandoned on 2026-05-14 once we confirmed `VISTA_ANALISIS_CECOS` is live (changes appear immediately). Nightly would have made P&L summary lag drill-down by up to a day — a user-visible regression worse than the cold-pickle tax. The current self-built hourly design preserves today's freshness contract. See [FACT_TABLE.md](FACT_TABLE.md) "What about the original Path A?" for the audit trail.

### Effort

| Item                                                                                       | Days |
|--------------------------------------------------------------------------------------------|------|
| Scheduler ETL extension + `fetch_pnl_summary_fast` + flag wiring + intercept in `_ensure_pl_stmt_cached` | 2.0 |
| Diff harness + cross-company validation                                                    | 1.0  |
| Per-company rollout + 48 h soak each (~2 days active, ~10 days elapsed)                    | 2.0 active |
| **Total elapsed**                                                                          | **~2 weeks, dominated by per-company soak windows** |

### Risks

See [FACT_TABLE.md](FACT_TABLE.md) "Risks". Headline items: SACRED drift via the aggregation step (mitigated by zero-diff gate), first-boot race before the scheduler builds the pickle (mitigated by `FileNotFoundError` fallback to row-level path), and disk-pickle staleness on flip-back (mitigated by `invalidate_cache`).

### Validation criteria

- Diff harness returns zero diffs across all `(company, year, month)` triples.
- Cold-worker first-click latency on FIBERLINE/FIBERTECH/CONSOLIDADO drops from ~10 s to <1 s.
- Worker peak RSS under steady-state browsing drops by ~150–250 MB (the `df_stmt` cache is now ~10 MB per cell instead of ~150–250 MB).
- Memory budget "After Phase 2" row holds.

### Hard prerequisites

- Scheduled refresh ([SCHEDULED_REFRESH.md](SCHEDULED_REFRESH.md)) is shipped and stable. The Phase 2 ETL piggybacks on its hourly cycle.
- **No DBA prerequisites.** Phase 2 is entirely in our hands.

### What NOT to do

- Do **not** modify `prepare_stmt`, `pl_summary`, `bs_summary`, the `np.select` rules in `transforms.py`, or any file under `backend/services/accounting/`. The fact pickle replaces the *fetch* step, not the *transform* step. The aggregation runs *after* `prepare_stmt`, on the SACRED-transformed DataFrame.
- Do **not** flip the flag for CONSOLIDADO first to "see the biggest win." CONSOLIDADO reads the 4 real-company pickles; if one company's aggregation has a bug, you'll spot it faster on a single-company rollout.
- Do **not** delete the row-level path. Detail drill-down depends on it, and so does the diff harness's reference side.
- Do **not** revive the nightly DBA-owned design without first re-evaluating the freshness contract. The current design exists because `VISTA_ANALISIS_CECOS` is live; if that changes, revisit.

---

## Phase 3 — Use the reclaimed headroom (threaded workers) (DEFERRED 2026-05-12)

> **Goal**: Convert the memory savings from Phases 1 + 2 into concurrency. Move from 3 sync workers (3 concurrent requests) to 3 gthread workers × 4 threads (12 concurrent requests) without crossing the memory ceiling.

**Why**: After Phase 1, workers are mostly stateless. The current sync model means one slow request blocks an entire worker's slot — so a single user clicking "load FIBERLINE detail" can stall 1/3 of the cluster for 30 s. With gthread workers, the same worker can serve other requests while the slow one waits on the DB or on Redis. This is the cheapest way to lift the concurrent-user ceiling from ~10 to ~25.

### What changes

1. **`backend/gunicorn.conf.py`** ([gunicorn.conf.py:5](../backend/gunicorn.conf.py#L5)): change `worker_class` default from `"sync"` to `"gthread"`, add `threads = int(os.environ.get("GUNICORN_THREADS", "4"))`. Keep `workers=3`.
2. **Bump `DB_POOL_SIZE` from 8 to 16** in `.env`. Default lives at [backend/config/settings.py:32](../backend/config/settings.py#L32). Reason: 3 workers × 4 threads = 12 concurrent requests, each potentially holding a connection while running 1–2 queries. 16 gives one connection per concurrent request plus a 33% buffer.
3. **Re-verify thread safety**:
   - `LRUTTLCache` uses `threading.Lock` — safe.
   - `_get_inflight_lock` — safe, designed for this.
   - `RedisLRUTTLCache` (Phase 1) — `redis-py` is thread-safe per the docs (verify with the version pinned in `requirements.txt`).
   - pyodbc connections are **not** thread-safe — `_fetch_with_own_conn` at [backend/data/fetcher.py:63](../backend/data/fetcher.py#L63) already gives each fetch its own connection via the pool. Good.
   - Pandas operations release the GIL only inconsistently; expect threads to serialize on CPU-bound transforms. That's fine — the win is on I/O-bound waits (DB, Redis), which is most of the request time.
4. **Grafana / metrics**: add a basic dashboard (or extend the Phase 0 `mem_monitor` log) tracking concurrent-request count, per-endpoint p95 latency, Redis hit ratio, worker RSS. This was Tier 3.3 in the old doc — formalized here because Phase 3 is the first phase whose tuning needs metrics to be honest.

### Effort

| Item                          | Days |
|-------------------------------|------|
| gunicorn.conf.py edit + tests | 0.5 |
| DB_POOL_SIZE tune + load test | 1.0 |
| Grafana / dashboard           | 1.0 (can be deferred but not by much) |
| Staging soak under load       | 0.5 |
| **Total**                     | **~3 working days** |

### Risks

- **Without Phase 1, this phase causes OOM.** Three workers × four threads × one CONSOLIDADO load each = ~7.2 GB of pandas state, well past the 5 GB MemoryMax. This is the hardest prerequisite in the plan.
- **Threading bugs are subtle.** The single-flight locks are the most exposed surface. Mitigation: a parallel-curl test from staging — `for i in $(seq 1 12); do curl ... & done; wait` — must show exactly one DB fetch in the logs for the same `(company, year)`.
- **pyodbc pool exhaustion** under unexpected query patterns. Mitigation: log pool-wait time; alert if it crosses 1 s.
- **No SACRED interaction.** Threading the worker doesn't change data semantics. But pandas DataFrames are *not* safe to mutate from multiple threads — verify all mutation in `accounting/transforms.py` and `accounting/aggregation.py` happens on locally-created DataFrames, not on objects passed in from cache. Spot-check: `prepare_stmt` returns a new DataFrame via `.copy()`; confirm before promoting.

### Validation criteria

- 12 concurrent simulated users (3 workers × 4 threads worth) browsing distinct companies for 10 min with no 500s, no OOM, p95 < 5 s on cache hits.
- Worker RSS stays under 400 MB each; Redis under 2 GB; total system memory above 1 GB free throughout.
- Grafana shows the cluster handling sustained 8 RPS without queue depth growing.

### Hard prerequisites

- **Phase 1 must be complete.** Non-negotiable. Threaded workers without shared Redis cache = guaranteed OOM, worse than the 2026-05-12 incident because it'll trigger under normal traffic, not just at boot.
- Phase 0 memory log is in place to confirm we stayed under budget.

### What NOT to do

- Do **not** raise `workers` from 3 to 4 "since each worker is smaller now." More workers = more independent Redis connections + more independent disk-cache pickles in flight. Threads are the cheap axis; processes are not.
- Do **not** raise `threads` past 4 without rerunning the load test. Pandas + GIL means returns diminish fast.
- Do **not** ship Phase 3 in the same maintenance window as Phase 1. They need separate burn-in periods.
- Do **not** skip the Grafana / metrics step. Phase 3 is the first phase that needs measurement to tune; without it the next regression will look exactly like 2026-05-05 — invisible until a user reports it.

---

## Phase 4 — DBA index work

> **Goal**: Reduce DB-side query latency on the `VISTA_ANALISIS_CECOS` path. Out of our hands; included for completeness.

**Why**: Even with Redis caching and the fact table, the first user after a deploy still triggers a row-level fetch for detail drill-down, and CONSOLIDADO's full-year scan (`_fetch_consolidated` in [backend/data/fetcher.py](../backend/data/fetcher.py)) still hits the view. If the underlying tables behind the view don't have a covering index on `(CIA, FECHA, CUENTA_CONTABLE)`, those cold fetches will always be slow.

### What changes

- DBA work, not ours. See [SQL_INDEX_RECOMMENDATIONS.md](SQL_INDEX_RECOMMENDATIONS.md) for the proposed index.
- Action items for the DBA team:
  1. Confirm `(CIA, FECHA, CUENTA_CONTABLE)` indexing on underlying tables.
  2. Check `sys.dm_db_missing_index_details` for suggestions.
  3. Schedule a maintenance window to add the covering index.
  4. Verify auto-stats on those tables.
  5. Evaluate making the view itself materialized.

### Effort

Ours: ~0.5 days (write up the request, hand to DBA, review their work). Theirs: depends on their schedule.

### Risks

- A bad index choice could slow other consumers of the view (BI tools, etc.). Mitigation: this is the DBA's call, not ours.
- Index build takes a maintenance window; coordinate with the finance team's reporting cycle.

### Validation criteria

- Cold-cache fetch of FIBERLINE/2026 P&L (currently ~10–30 s — verify before shipping) drops to < 5 s.
- DB CPU on the SQL Server during peak Fiberlux usage drops measurably; confirm with the DBA.

### Hard prerequisites

None — Phase 4 can run in parallel with any other phase. It's gated only on DBA availability.

### What NOT to do

- Do **not** create indexes ourselves on a DB we don't own.
- Do **not** treat Phase 4 as a substitute for Phase 1 or Phase 2. A faster query that returns 8.4 M rows still allocates 600 MB of pandas — the index helps latency, not memory.

---

## Sequencing summary

Active path as of 2026-05-12:

```
Phase 0 (in flight) ──▶ Scheduled refresh ──▶ Phase 2 (queued)

        Phase 1 (DEFERRED) ── Phase 3 (DEFERRED)
        Phase 4 (DBA, parallel; gated only on DBA availability)
```

- **Phase 0** is partly shipped (3 commits on `dev`); operational steps (`.env`, systemd) still pending on staging + prod.
- **Scheduled refresh** is the next major work — see [SCHEDULED_REFRESH.md](SCHEDULED_REFRESH.md).
- **Phase 2** stays queued; it shrinks the working set the scheduler has to handle.
- **Phase 1 + Phase 3** are deferred. They are not part of the active plan.
- **Phase 4** is gated on the DBA only and unrelated to the scope change.

## What this doc is not

This is not a menu. The phases above were agreed; new ideas (alternative cache stores, container orchestration, splitting the app into services, query rewrites in SQL Server) need a separate discussion before they go into a roadmap. If you find yourself wanting to add Phase 5, write it up and pitch it — don't append it here.
