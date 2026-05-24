# Scaling Roadmap

> **Status**: Phase 0 partially shipped 2026-05-12 (3 commits on `dev`). **Scope change 2026-05-22**: the active path is now the SQL views roadmap ([SQL_VIEWS_ROADMAP.md](SQL_VIEWS_ROADMAP.md)) — moving classification and aggregation into the database is structurally cheaper than every Python-side mitigation in this doc. Phase A (P&L classification) shipped; the scheduled refresh was deleted in Phase A.5; Phase 1 (Redis), Phase 2 (fact pickles), and Phase 3 (gthread) were either deleted or deferred because the SQL views path makes them unnecessary. See "Scope change 2026-05-22" below.
> **Owner**: Backend team.
> **Last updated**: 2026-05-22 (SQL views scope change).
> **Supersedes**: Tier 2 and Tier 3 of [CONCURRENCY_SCALING.md](CONCURRENCY_SCALING.md). That doc's Tier 1 (timeout bump, single-flight, warmup post-mortem) remains the historical record for the 2026-05-05 incident and the 2026-05-12 warmup revert; do not re-litigate those sections here.

## Why this document exists

[CONCURRENCY_SCALING.md](CONCURRENCY_SCALING.md) was written reactively after a single `HYT00` timeout. Tier 1 shipped and removed that failure mode. Tier 1.2 (startup warmup) was implemented on 2026-05-12, OOM-killed prod twice the same day, and was reverted.

That revert exposed the constraint this doc is built around: **the prod host is 5.8 GB RAM + 3.8 GB swap and cannot be expanded.** Everything below is framed around fitting the Fiberlux finance team (~10–25 concurrent users) into that fixed envelope without crashes.

This is capacity planning, not outage response. **As of 2026-05-22 the active capacity work has moved out of this document.** The team gained the ability to create views on the source SQL Server, which is a structural unlock: classification and aggregation can move out of pandas and into SQL, cutting both per-request CPU and per-worker memory at the source. [SQL_VIEWS_ROADMAP.md](SQL_VIEWS_ROADMAP.md) is the active plan; the phases below remain as the contingency spec if the SQL views path stalls or fails to deliver.

---

## Memory budget

The 5.8 GB ceiling is non-negotiable. Reference baseline (post-Phase-0 steady state):

| Consumer                                    | Steady state |
|---------------------------------------------|--------------|
| OS + nginx + sqlite + agents                | ~1.0 GB      |
| 3 gunicorn workers (peak resident)          | 3 × ~0.7 GB  |
| Headroom / page cache                       | ~1.5 GB      |
| Peak observed at last OOM (2026-05-12)      | 5.2 GB       |

> **The structural constraint**: today, each worker independently caches the same DataFrames. With 3 workers and FIBERLINE_2025's `df_stmt` at ~400 MB in memory, three users hitting three workers can pull the same ~1.2 GB into RAM simultaneously. **SQL views Phase C collapses each cached payload from ~400 MB to ~10 KB** by serving pre-aggregated summary rows directly — the duplication stops mattering once the duplicated thing is two orders of magnitude smaller. See [SQL_VIEWS_ROADMAP.md](SQL_VIEWS_ROADMAP.md).

---

## Hard limits we accept

- The box is **5.8 GB RAM + 3.8 GB swap**, confirmed by the user 2026-05-12; not expandable in this fiscal window.
- Swap is effectively useless under interactive load — observed exhaustion during the warmup OOM. Treat the working set as if swap doesn't exist.
- The realistic post-SQL-views ceiling on this hardware is roughly **25–30 concurrent active users** (verify by load test before promising more). Beyond that, only more RAM helps; no software change in this plan removes that wall.
- The SQL Server view `REPORTES.VISTA_ANALISIS_CECOS` (~8.4 M rows) is owned by the DBA team and is **live** (changes posted by finance appear immediately). DBA cooperation is required for the SQL views path (DDL deploys) and for index work — both flow through the same channel.
- The accounting transformation pipeline ([CODING_PATTERNS.md](CODING_PATTERNS.md) "Accounting Logic — SACRED, DO NOT MODIFY") is fixed. Any phase that touches data flowing into it must produce bit-identical numbers. For Phase A the SQL view's parity against Python was enforced by `sql/parity_check.py`, which was deleted alongside the Python pipeline once Step 4 landed; the SQL view is now the source of truth (see [SQL_VIEWS_ROADMAP.md](SQL_VIEWS_ROADMAP.md) "Drift mitigation").

---

## Scope change 2026-05-22: SQL views supersede every Python-side mitigation

On 2026-05-22 the team received permission to create views in the source SQL Server (`REPORTES` schema and the per-CIA schemas). This unlocks a fundamentally different lever: **push work out of Python and into the database**, where it can be shared across all workers without RAM duplication and where the engine is much faster at the GROUP BY than pandas is. Active plan lives in [SQL_VIEWS_ROADMAP.md](SQL_VIEWS_ROADMAP.md).

What SQL views deliver:

1. **Classification moves to SQL.** `prepare_pnl → filter_for_statements → assign_partida_pl` and the BS equivalents collapse into view definitions. The CASE expression that today runs in a Python `np.select` over 8.4M rows runs once in the engine's query plan instead. Benchmarked 3.4–7.9× speedup on aggregated fetches.
2. **Aggregation moves to SQL (Phase C).** Instead of pulling 8.4M rows and grouping in pandas to produce ~100 summary rows, the dashboard fetches the ~100 rows directly. The DataFrame held per worker shrinks roughly two orders of magnitude. This is the move that makes concurrent load comfortable on the 5.8 GB box, because the per-request and per-worker memory cost both collapse at the source.
3. **One source of truth.** Today the same classification rules exist in Python and as embedded knowledge in any SQL the finance team writes for Excel-via-ODBC. The view collapses both into one place.

What this changed for every prior phase in this doc:

| Prior phase                          | Disposition |
|--------------------------------------|-------------|
| Phase 0 — Safety nets                | **Still in place.** The cgroup ceiling and LRU caps remain as belt-and-suspenders; nothing here is undone by the SQL views work. |
| Scheduled refresh (shipped 2026-05-12) | **Deleted 2026-05-22.** Misbehaving in prod (FIBERLINE never finished hourly window; cycles clobbered each other; only warmed 1 of 3 workers anyway). Phase A makes per-request fetches fast enough that no pre-warming is needed, and Phase C will make them sub-second. `refresh_scheduler.py` removed; see [SQL_VIEWS_ROADMAP.md Phase A.5](SQL_VIEWS_ROADMAP.md). |
| Phase 1 — Redis-backed cache         | **Deferred indefinitely.** Buys only sub-hour freshness over the current design, which finance has not requested. Phase C also shrinks the cached payload two orders of magnitude, so the cross-worker duplication Redis was designed to fix stops mattering. Section retained as contingency spec only. |
| Phase 2 — Monthly fact pickles       | **Deleted 2026-05-22.** SQL views Phase C builds the same aggregated artifact in the database engine, shared across workers, with no per-worker pickle-load tax. `docs/FACT_TABLE.md` deleted; no fact-pickle code shipped. |
| Phase 3 — gthread workers            | **Deferred indefinitely.** Once classification + aggregation move to SQL, per-request CPU drops far enough that 3 sync workers comfortably cover the user load. |
| Phase 4 — DBA index work             | **Folded into the SQL views workstream.** Indexes on `(CIA, FECHA, CUENTA_CONTABLE)` of the underlying tables remain valuable; the conversation moves into the SQL views deployment cycle. |

**Why this is the right pivot.** Every Python-side phase in this document was a defense against the wrong constraint. The real constraint was that we were doing the engine's job (classification, aggregation) in pandas on a 5.8 GB box. SQL views remove the work from our box rather than make our box tolerate the work. That's a structural fix, not a mitigation.

**The active plan now lives in [SQL_VIEWS_ROADMAP.md](SQL_VIEWS_ROADMAP.md).** Sections below remain for audit and as contingency specs if the SQL views path stalls.

---

## Operational guardrails

The "never again" list from the 2026-05-12 post-mortem. These apply to every phase below.

1. **Never eagerly load all companies at boot.** Warmup is banned on this hardware; rely on the natural cache fill driven by user requests. Re-read the warmup post-mortem in [CONCURRENCY_SCALING.md](CONCURRENCY_SCALING.md) section 1.2 before proposing anything that walks `COMPANIES` in a loop.
2. **Never multiply the working set by the number of workers.** Any cache that lives in a worker process is paid for N times. The SQL views path (active plan) addresses this by shrinking the cached payload at the source, so the duplication stops mattering. If a cache entry is still large after the SQL views land, it does not belong in worker memory.
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

   With 4 companies × 2 years = 8 cells, 6 entries per bucket means the LRU evicts companies a worker hasn't touched in 30 min. The pre-fetch chain (`_prefetch_bs_background`, `_prefetch_prev_year_background`, `_prefetch_pl_sections_background`) keeps the most-recently-used pair hot.

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
- **Smaller LRUs could increase cache-miss rate for users hopping companies.** Mitigation: the disk cache at `backend/services/.stmt_cache/` (verified 2026-05-12: 157 MB for FIBERLINE_2025 down to 2.1 MB for FIBERLUX_2026) absorbs evictions cheaply — `_try_pl_stmt_from_disk` re-hydrates a worker in seconds, not minutes.
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
> **Why this is no longer the right move**: Phase 1 was written to solve two problems at once — (a) cross-worker cache duplication and (b) slow cold cache reads. SQL views Phase A + C address both directly: classification + aggregation move into SQL, so per-request fetches become fast (Phase A: ~6 s for FIBERLINE; Phase C target: sub-second) and the cached payload shrinks from ~400 MB to ~10 KB per `(company, year)` (Phase C). Once cached entries are kilobytes, the fact that each worker keeps its own copy stops being economically interesting — cross-worker duplication becomes a footnote, not a bottleneck.
>
> **What Phase 1 would still uniquely solve**: real-time freshness across workers. If finance ever needs sub-minute freshness — for example, if a workflow emerges where users post a journal entry and immediately refresh to confirm it appeared — Phase 1 is the way to deliver that. Redis-backed caching with on-request fills is the answer if and only if that requirement appears.
>
> **Do not implement Phase 1 unless** finance has explicitly asked for sub-hour data freshness. Without that requirement, Phase 1's complexity (new dependency, new failure mode, new ops surface) buys nothing the current design doesn't already deliver.
>
> **Goal (if revived)**: Take the DataFrames out of gunicorn process memory entirely, so worker RSS is dominated by code + per-request scratch, not by accumulated cache state.

**Why (original framing, pre-pivot)**: Today, 3 workers × peak ~1.5 GB resident is the structural ceiling, and most of that 1.5 GB is cached DataFrames duplicated across workers. Moving the cache into a single Redis process with `maxmemory 2gb maxmemory-policy allkeys-lru` reclaims roughly 2 GB of duplicated state while bounding the cache itself with an eviction policy we control. Workers become almost stateless. As a free upgrade, cross-process single-flight (`_CrossProcLock`) collapses from a `fcntl.flock` dance into a one-liner `SET NX EX`.

### What changes

1. **New file `backend/services/cache_redis.py`** (~150 lines): a class `RedisLRUTTLCache` that exposes the same `get(company, year)`, `set(company, year, value)`, `pop(company, year)`, `clear()`, `stats()` surface as `LRUTTLCache` at [data_service.py:54](../backend/services/data_service.py#L54). Values are pickled (use `pickle.HIGHEST_PROTOCOL`; pandas pickles are already the disk format, so the cost is known: ~1–3 s round-trip for FIBERLINE_2025's 157 MB pickle — single-flight absorbs concurrent callers).
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

- **Pickle serialization cost is now on every cache hit, not just disk miss.** For FIBERLINE_2025 at 157 MB, a Redis hit means ~1–3 s of pickle work per worker per fetch (verify on staging with `timeit`). Mitigation: the value goes into the in-process `pl_df` / `pl_preagg` caches on hit, so the same worker pays once per TTL window, not per request. Net effect on cache-hit p95 should still beat a cold DB fetch by an order of magnitude.
- **Redis is now a single point of failure.** Mitigation: the fallback path above. Add a synthetic check ("can I `PING` Redis?") to the existing health endpoint so the load balancer / monitoring catches a dead Redis even if requests still succeed.
- **`SET NX EX 300` could leak a lock if a worker dies mid-fetch.** Mitigation: 300 s TTL matches `DB_QUERY_TIMEOUT`, so worst case other workers wait 5 min then retry. Acceptable. Do **not** set a longer TTL just because pickle is slow.
- **No SACRED interaction.** Phase 1 changes only the storage layer. No accounting code is touched. Still, run the staging diff (load FIBERLINE/2026, open every section, compare totals to prod) before promoting.
- **Deployment ordering matters.** The staging→prod workflow ([DEPLOYMENT.md](DEPLOYMENT.md)) requires Redis to be installed on prod *before* `./promote.sh` runs, or the new code will degrade to fallback on first boot. Ship Redis install as a manual ops step in the same maintenance window.

### Validation criteria

- Stop Redis (`sudo systemctl stop redis-server`). The app must still answer requests, with cache-miss log lines and degraded latency. No 500s.
- Restart Redis. Cache hits resume within one TTL window.
- With Redis up, restart gunicorn. The first request per `(company, year)` triggers a Redis cache fill from disk (since pre-Phase-1 disk caches still exist); the second request from a different worker is served from Redis with no DB hit. Verify via `redis-cli MONITOR` and `grep "P&L fetch" backend/logs/error.log` (should be silent on the second request).
- Worker RSS during steady-state browsing of all 4 companies drops from ~1.0–1.5 GB to ~300 MB (verify on staging).
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

## Phase 3 — Use the reclaimed headroom (threaded workers) (DEFERRED 2026-05-12)

> **Goal**: Convert memory savings (from Phase 1 if revived, or from SQL views Phase C in the active plan) into concurrency. Move from 3 sync workers (3 concurrent requests) to 3 gthread workers × 4 threads (12 concurrent requests) without crossing the memory ceiling.

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

- **Without Phase 1, this phase causes OOM.** Three workers × four threads × one FIBERLINE load each = ~4.8 GB of pandas state, perilously close to the 5 GB MemoryMax. This is the hardest prerequisite in the plan.
- **Threading bugs are subtle.** The single-flight locks are the most exposed surface. Mitigation: a parallel-curl test from staging — `for i in $(seq 1 12); do curl ... & done; wait` — must show exactly one DB fetch in the logs for the same `(company, year)`.
- **pyodbc pool exhaustion** under unexpected query patterns. Mitigation: log pool-wait time; alert if it crosses 1 s.
- **No SACRED interaction.** Threading the worker doesn't change data semantics. But pandas DataFrames are *not* safe to mutate from multiple threads — verify all mutation in `accounting/transforms.py` and `accounting/aggregation.py` happens on locally-created DataFrames, not on objects passed in from cache. Spot-check: `prepare_pnl_from_view` and `prepare_bs_stmt` start with `.copy()` of their input; confirm before promoting.

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

## Phase 4 — DBA index work (folded into SQL views deployment cycle)

> **Status**: As of 2026-05-22, this conversation moves into the same DBA channel that handles SQL views DDL deploys. Index work and view deploys are both small DBA tasks; bundling them avoids two separate ops conversations.
>
> **Goal**: Reduce DB-side query latency on the `VISTA_ANALISIS_CECOS` path. Out of our hands; included for completeness.

**Why**: Even with the SQL views in place, the first user after a deploy still triggers a row-level fetch for detail drill-down. If the underlying tables behind `VISTA_ANALISIS_CECOS` don't have a covering index on `(CIA, FECHA, CUENTA_CONTABLE)`, those cold fetches will always be slow. After SQL views Phase A/B land, the same index also accelerates the `VISTA_PNL_PREPARADO` / `VISTA_BS_PREPARADO` plans (they read from the same underlying tables via the per-CIA `VISTA_ANALISIS_CECOS` views).

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
- Do **not** treat Phase 4 as a substitute for the SQL views path. A faster query that returns 8.4 M rows still allocates 600 MB of pandas — the index helps latency, not memory. SQL views Phase C is what removes the memory cost.

---

## Sequencing summary

Active path as of 2026-05-22:

```
Phase 0 (shipped) ──▶ SQL views Phase A (shipped) ──▶ A.5 scheduler deleted (shipped)
                                                        ──▶ Phase B ──▶ Phase C ──▶ C+1 simplification

        Phase 1 (DEFERRED) ── Phase 3 (DEFERRED)
        Phase 4 (folded into SQL views deployment cycle)
```

- **Phase 0** is shipped on `dev`; operational steps (`.env`, systemd) still pending on staging + prod and continue to ship independently of the SQL views work.
- **Scheduled refresh** was shipped 2026-05-12 and deleted 2026-05-22. Reasons recorded in [SQL_VIEWS_ROADMAP.md Phase A.5](SQL_VIEWS_ROADMAP.md). Phase A makes per-request fetches fast enough that pre-warming is unnecessary.
- **SQL views Phase A → B → C** is the active work — see [SQL_VIEWS_ROADMAP.md](SQL_VIEWS_ROADMAP.md). Phase A (P&L classification in SQL) shipped 2026-05-22. Phase B (BS classification) is next. Phase C pushes summary aggregation into SQL and is the move that buys structural concurrency headroom.
- **Phase C+1** is a queued simplification pass that becomes possible once Phase C is in prod: drop worker count, remove disk pickle layer, remove single-flight flock, possibly preload-at-startup. Most of the current cache complexity exists to compensate for problems Phase C deletes; C+1 sheds those layers. See [SQL_VIEWS_ROADMAP.md Phase C+1](SQL_VIEWS_ROADMAP.md). Also records the decision *not* to pursue task-typed workers — operational complexity doesn't justify it for the internal-tool traffic profile.
- **Phase 1 and Phase 3** are deferred contingency specs, not part of the active plan. (Phase 2 was deleted on 2026-05-22 once SQL views Phase C made it obsolete.)
- **Phase 4** (DBA index work) is folded into the SQL views deployment cycle; the index conversation moves into the same DBA channel that handles view DDL deploys.

## What this doc is not

This is not a menu. The phases above were agreed; new ideas (alternative cache stores, container orchestration, splitting the app into services, query rewrites in SQL Server) need a separate discussion before they go into a roadmap. If you find yourself wanting to add Phase 5, write it up and pitch it — don't append it here.
