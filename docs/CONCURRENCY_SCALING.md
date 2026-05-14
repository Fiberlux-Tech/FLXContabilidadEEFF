# Concurrency & Scaling Plan

> **Status**: Tier 1.1 + 1.3 shipped 2026-05-12. Tier 1.2 was implemented and reverted the same day — see post-mortem under that section. Implement remaining tiers in order.
> **Owner**: Backend team.
> **Last updated**: 2026-05-12.

## Why this document exists

On 2026-05-05 12:35 PE, a user (Cesar) hit the following error loading FIBERTECH/2026:

> `Failed to fetch data for FIBERTECH/2026: Execution failed on sql ... Query timeout expired (0)`

A second user-facing failure followed at 12:54 PE on the detail dialog. Both errors trace back to the same root cause: **the SQL Server query against `REPORTES.VISTA_ANALISIS_CECOS` exceeded `DB_QUERY_TIMEOUT=120s`** (configured in `.env`).

### What we proved during the investigation

1. **The query itself is fast under no load.** Re-running the exact failing SQL: 1.0s for the detail query, 1.8s for a P&L full year, ~5s for an 8-query worst case from a single client.
2. **Concurrent users multiply query time dramatically.**
   - 1 user (solo): ~2s per query
   - 2 users at once: ~41s per query (~20× slowdown)
   - 4+ users at once: extrapolates past 120s → **timeout**
3. **Server logs confirm the pattern.** During the failure window (`2026-05-05 17:35–19:37 UTC`), five separate `HYT00 Query timeout expired` errors landed within ~2 hours. Each was preceded by a cache miss that forced a fresh DB fetch.
4. **Multi-process Gunicorn deploys make it worse.** We run 3 sync workers, each with its own in-memory cache. When 3 users land on 3 different workers, each worker fires its own DB query — 3× the load for the same data.

This document is the roadmap for fixing it before usage grows further.

---

## Architecture today (so the plan makes sense)

```
nginx (10.100.50.4:80)
   │
   ▼
Gunicorn (3 sync workers, port 5000)         <-- each worker has its OWN _caches dict
   │
   ▼
backend/services/data_service.py
  • In-memory LRU+TTL cache (per worker)
  • Disk cache: backend/services/.stmt_cache/*.pkl (shared across workers)
   │
   ▼
backend/data/fetcher.py
  • ThreadPoolExecutor(max_workers=5)         <-- per-request parallelism
  • Submits up to 4 queries per Resumen load
   │
   ▼
backend/data/db.py
  • pyodbc connection pool (size 8 per worker)
  • DB_QUERY_TIMEOUT=120s (set in .env)
   │
   ▼
SQL Server 192.168.30.118 — REPORTES.VISTA_ANALISIS_CECOS (~8.4M rows)
```

**Key facts to internalize before reading the fixes:**

- A single `Resumen` load fires **2 parallel queries** (P&L full year + BS cumulative) when `need_pdf=False`. With prev-year data needed it's **4**.
- Each Gunicorn worker is a **separate Python process** with its own in-memory caches. The disk cache is the only shared layer.
- The detail endpoint forces a fresh fetch when the in-memory cache misses — so post-deploy, the first user to click a detail row hits the DB.
- We do **not** own the SQL Server. The view is shared with other consumers (BI tools, etc.). Index changes require coordination with the DBA.

---

## Tier 1 — Low effort, high impact (DO FIRST)

These changes individually mitigate the failure mode you saw on 2026-05-05. Together they remove ~95% of cache-miss-induced timeouts.

### 1.1 — Bump `DB_QUERY_TIMEOUT` to 300s

**Why**: The current 120s ceiling is too tight for FIBERLINE/FIBERTECH under any meaningful concurrent load. Logs show legitimate (non-timed-out) queries running 150–360s when the DB is busy. 300s gives queries enough headroom to finish before throwing, while still cutting off truly hung connections.

**Risk**: ~Zero. The browser fetch already waits longer than this; users currently see "loading" for 2–3 minutes during cold loads.

**Where**:
- File: `.env` line 26 (production)
- File: `.env.development` if present
- File: `.env.production` if present

**Change**:
```diff
- DB_QUERY_TIMEOUT=120
+ DB_QUERY_TIMEOUT=300
```

**Validation**:
1. Run `./deploy.sh` (or restart `flxcontabilidad`)
2. Tail `backend/logs/error.log` and confirm no startup errors
3. Hit the dashboard with a cold cache (after restart) — first load should complete

**Done when**: a cold-cache load of FIBERLINE/2026 completes successfully without throwing `HYT00`.

---

### 1.2 — Pre-warm the cache on startup — **ATTEMPTED AND REVERTED 2026-05-12**

> **Outcome**: Implemented as `backend/services/warmup.py` + gunicorn `post_worker_init` hook, ran successfully on staging, then OOM-killed prod twice within an hour (16:05 and 16:07 PE). Reverted entirely the same day. **Do not re-attempt on this hardware.** Keeping this section as a post-mortem.
>
> **Why it failed**: The prod server is 5.8 GB RAM + 3.8 GB swap. Warmup loaded df_stmt for all 5 companies (FIBERLINE/FIBERLUX/FIBERTECH/NEXTNET/CONSOLIDADO) × current year, plus prev-year via the existing `_prefetch_prev_year_background` chain triggered by each `load_pl_data` call. CONSOLIDADO_2025 alone is 269 MB on disk → ~600 MB in memory; CONSOLIDADO_2026 is 98 MB → ~200 MB; 4 real companies × 2 years adds ~1.5 GB more. With 3 gunicorn workers (only 1 warms, but the other 2 still consume RAM), nginx, and the OS, peak memory hit 5.2 GB and the OOM killer terminated gunicorn mid-warmup. Systemd auto-restarted the service, the new worker started warmup again, and the cycle repeated.
>
> **Why the natural cache works fine without warmup**: `load_pl_data` already triggers `_prefetch_bs_background`, `_prefetch_prev_year_background`, and `_prefetch_pl_sections_background` on the first request for any `(company, year)`. Combined with Tier 1.3 single-flight, the first user pays a bounded wait (~10–30s for an uncached company under the new 300s timeout) and every subsequent user gets the cache. The LRU+TTL also evicts entries users aren't touching, so memory tracks actual usage rather than theoretical worst case — exactly the property warmup deliberately fought.
>
> **What to do if first-user latency ever becomes a real complaint**: don't bring warmup back. Add a tiny post-deploy cron that issues one HTTP request per company serially (e.g. `curl -s -X POST .../api/data/load-pl ...` once for each of the 4 companies). The cron user pays the cost, the existing background prefetch chain warms BS + prev-year + sections, and memory peaks at ~one-company-worth instead of all-five-at-once because the requests are sequential.
>
> **Original plan (kept for context, do not implement):**

**Why**: Today, when the service restarts (deploy or systemd reload), all in-memory caches are empty. The first user to log in triggers a synchronous DB fetch in their request thread. If two users log in simultaneously after a deploy, each worker fetches → query contention → timeout. **This is exactly what hit Cesar.**

The disk cache (`backend/services/.stmt_cache/*.pkl`) already persists transformed `df_stmt` DataFrames across restarts. We just need to load them into memory at startup, and fetch+save any that are missing.

**Risk**: Adds ~30–60s to startup if disk caches are missing. Mitigated by running pre-warm in a background thread after the worker is ready to serve.

**Where**:
- New file: `backend/services/warmup.py`
- File: `backend/app.py` — register a post-fork hook
- File: `backend/gunicorn.conf.py` — add `post_worker_init` hook

**Implementation outline**:

```python
# backend/services/warmup.py
import logging
import threading
from datetime import datetime

from services.data_service import load_pl_data, load_bs_data

logger = logging.getLogger("flxcontabilidad.warmup")

COMPANIES = ("FIBERLINE", "FIBERLUX", "FIBERTECH", "NEXTNET")

def warmup_async() -> None:
    """Spawn a background thread that warms the cache for all companies/current year.

    Runs in a thread so worker startup is not blocked. Failures are logged and
    swallowed — a warmup failure must not crash the worker.
    """
    threading.Thread(target=_warmup_blocking, name="cache-warmup", daemon=True).start()

def _warmup_blocking() -> None:
    year = datetime.now().year
    for company in COMPANIES:
        for label, fn in (("P&L", load_pl_data), ("BS", load_bs_data)):
            try:
                logger.info("warmup: %s %s/%d starting", label, company, year)
                fn(company, year)
                logger.info("warmup: %s %s/%d done", label, company, year)
            except Exception as e:
                logger.warning("warmup: %s %s/%d failed: %s", label, company, year, e)
```

**Hook into Gunicorn** (only one worker should warm to avoid hammering the DB on startup):

```python
# backend/gunicorn.conf.py — add at bottom
def post_worker_init(worker):
    """Run once per worker after fork. Only the first worker warms; others rely
    on the disk cache that the first worker writes."""
    if worker.age == 0 and getattr(worker, 'pid', 0) % 3 == 0:
        # Heuristic: only ~1 in 3 workers warms. Adjust if you want stricter.
        from services.warmup import warmup_async
        warmup_async()
```

**Better alternative** (recommended): use a `--preload`-friendly file lock so exactly one worker warms:

```python
# backend/services/warmup.py — at top
import fcntl
from pathlib import Path

_LOCK_PATH = Path("/tmp/flx_warmup.lock")

def warmup_async() -> None:
    """Try to acquire an exclusive non-blocking file lock. If we get it, we are
    the elected warmer; if not, another worker is already warming."""
    fh = open(_LOCK_PATH, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fh.close()
        return  # another worker has it, that's fine
    threading.Thread(target=_warmup_blocking, args=(fh,), name="cache-warmup", daemon=True).start()

def _warmup_blocking(lockfile) -> None:
    try:
        # ... same body as above ...
        pass
    finally:
        lockfile.close()  # releases the flock
```

**Validation**:
1. Restart service.
2. Tail `backend/logs/error.log`; within 60–120s you should see `warmup: P&L FIBERLINE/2026 done` for all 4 companies.
3. Log in as a user immediately after restart and load the dashboard. **First load should be served from cache (sub-second).**
4. `ls -la backend/services/.stmt_cache/` — pickles for current year should be present and recent.

**Done when**: cold-deploy → 4 user logins in parallel → no DB queries fired (all served from warmed cache).

---

### 1.3 — Single-flight: deduplicate concurrent fetches

**Why**: Even with warmup, a user clicking "refresh" or hitting a not-yet-warmed `(company, year)` triggers a DB fetch. If two users do this at the same moment in different workers, **both** fire the query. The single-flight pattern coalesces concurrent identical fetches: the second caller waits for the first instead of duplicating the work.

There are two layers where this matters:

#### 1.3a — In-process single-flight (per worker)

Inside one Gunicorn worker, two requests landing on different threads can both miss the cache and both call `_ensure_pl_stmt_cached`. Add a per-key lock dict:

```python
# backend/services/data_service.py — near the cache definitions
import threading
_inflight_locks: dict[tuple[str, int, str], threading.Lock] = {}
_inflight_lock_guard = threading.Lock()

def _get_inflight_lock(company: str, year: int, kind: str) -> threading.Lock:
    key = (company, year, kind)
    with _inflight_lock_guard:
        lock = _inflight_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _inflight_locks[key] = lock
        return lock
```

Then wrap `_ensure_pl_stmt_cached` and `_ensure_bs_stmt_cached`:

```python
def _ensure_pl_stmt_cached(company, year, *, force_refresh=False):
    lock = _get_inflight_lock(company, year, "pl")
    with lock:
        # Re-check the cache under the lock — another thread may have just filled it
        cached = _caches["pl_stmt"].get(company, year)
        if cached is not None and not force_refresh:
            return cached, _caches["pl_preagg"].get(company, year), \
                   _caches["pl_preagg_ex_ic"].get(company, year), \
                   _caches["pl_preagg_only_ic"].get(company, year)
        # ... existing fetch + transform + cache code ...
```

**Risk**: Adds a critical section that serializes within one company/year. This is exactly what we want — it prevents duplicate DB hits without affecting other (company, year) pairs.

#### 1.3b — Cross-process single-flight (across workers)

The above only protects within one worker. To deduplicate across all 3 Gunicorn workers, you need a shared lock. Two options:

**Option A — File lock** (zero new dependencies, slightly clunky):
```python
import fcntl
def _acquire_cross_proc_lock(company, year, kind):
    path = Path(f"/tmp/flx_inflight_{company}_{year}_{kind}.lock")
    fh = open(path, "w")
    fcntl.flock(fh, fcntl.LOCK_EX)  # blocks until acquired
    return fh
```
The other workers block on `flock` until the elected one finishes and writes the disk cache. They then read from disk instead of DB.

**Option B — Redis** (cleaner, more flexible):
- Add `redis` to `requirements.txt`.
- Use `redis-py` `set(key, value, nx=True, ex=180)` to acquire a lock with TTL.
- Worker that loses the race polls the disk cache for ~30s waiting for the winner to finish.

**Recommendation**: Start with **Option A** (file lock) as part of Tier 1. It's 20 lines and zero new infrastructure. Move to Redis when you do Tier 2.4.

**Validation**:
1. Restart with empty disk cache (`rm backend/services/.stmt_cache/*.pkl`).
2. From two browsers, hit `/api/data/load-pl?company=FIBERTECH&year=2026` simultaneously.
3. Tail `backend/logs/error.log` — you should see **exactly one** `P&L fetch: ...` log line, not two. The second request should log "Serving cached..." after waiting briefly.

**Done when**: parallel curl test (`for i in 1 2 3 4; do curl ... &; done`) results in only one DB query in the logs.

---

### Tier 1 summary

**Actually shipped (2026-05-12):** 1.1 + 1.3. 1.2 was reverted same-day (see post-mortem above).

The realistic concurrency capacity went from **"3 simultaneous cold-cache users will fail"** to **"~10 simultaneous cold-cache users serialize cleanly on a single DB query, no timeouts"**. The DB is hit on `force_refresh=True` and on the very first call per `(company, year)` after a deploy — that first call is bounded by the new 300s pyodbc timeout and coalesces concurrent users via single-flight, so subsequent users wait on the lock rather than firing their own queries.

**Effort actually spent**: ~1 working day (matches estimate). Failed warmup attempt added ~1h of debugging + revert.

---

## Tier 2 — Medium effort, removes the bottleneck (do once Tier 1 is stable)

### 2.1 — Replace per-process in-memory cache with Redis

**Why**: Today every Gunicorn worker maintains its own `_caches` dict. In a 3-worker setup, the first user to hit each worker pays the cache-miss cost — even if a sibling worker already has the data hot. Add a 4th worker to scale horizontally and the problem worsens.

A shared Redis cache means **one fetch serves all workers**. It also enables Tier 1.3b cleanly (Redis SET NX is the canonical single-flight lock primitive).

**What changes**:
- New container/process: Redis on `localhost:6379` (or wherever you prefer).
- Replace `LRUTTLCache` ([backend/services/data_service.py:53](backend/services/data_service.py#L53)) with a thin wrapper that serializes pandas DataFrames to Parquet bytes (or pickle) and stores them in Redis with TTL.
- Same TTL semantics (30 min); same `get`/`set`/`pop` interface. Callers don't change.

**Critical implementation detail**: pickled DataFrames are large (FIBERTECH `df_stmt` is ~32MB). Redis can handle this, but watch memory. Set `maxmemory` and `maxmemory-policy allkeys-lru` so old entries get evicted.

**Risk**: Adds a new infrastructure dependency. If Redis goes down, the app needs to fall back to local cache (don't let it cascade-fail). Wrap Redis calls in try/except and log degradation.

**Where**:
- New file: `backend/services/cache_redis.py`
- Modify: `backend/services/data_service.py:53-130` (replace `LRUTTLCache` instantiation)
- Modify: `requirements.txt` — add `redis>=5.0`
- Modify: `setup_infrastructure.sh` — install + enable Redis service
- New: systemd unit for Redis (or use the distro's)

**Effort estimate**: 2–3 days including testing the failover path.

**Validation**:
1. With Redis running, restart the app. Load FIBERTECH from worker A.
2. Kill worker A's process (`kill -9` one of the gunicorn pids). Gunicorn respawns it.
3. Load FIBERTECH again — should be served from Redis (cached), no DB query.
4. Stop Redis. App should still respond, just slower (falls back to fetching).

---

### 2.2 — Build a monthly aggregate fact table

> **Superseded 2026-05-14.** This section described a DBA-owned nightly fact table on SQL Server. That design was replaced by self-built hourly fact pickles after we confirmed `VISTA_ANALISIS_CECOS` is live; nightly would have made P&L summary lag drill-down by up to a day. **Active spec lives in [FACT_TABLE.md](FACT_TABLE.md); roadmap-level summary in [SCALING_ROADMAP.md](SCALING_ROADMAP.md) Phase 2.** The text below is preserved as the original Tier 2.2 proposal for historical context only — do not implement against it.

**Why**: `REPORTES.VISTA_ANALISIS_CECOS` returns row-level journal entries — 8.4M rows, growing. Almost everything the dashboard does is sum-by-month. A nightly job that pre-aggregates to `(CIA, year, month, cuenta_contable, centro_costo, debito, credito)` gives you a table with **~100K rows total, not 8.4M**, and queries against it run in ms.

The detail drilldown still needs row-level data, but only for one `(partida, month)` at a time — that's a small filtered slice, not a full-year scan.

**What changes**:
- New SQL Agent job (or cron + SQL script) on the SQL Server: `nightly_build_REPORTES_FACT_MENSUAL.sql` that runs at 02:00 PE.
- New table: `REPORTES.FACT_ANALISIS_MENSUAL` with appropriate clustered index `(CIA, ANIO, MES, CUENTA_CONTABLE)`.
- Modify: `backend/data/queries.py` — add `fetch_pnl_summary_fast()` that hits the fact table. Keep `fetch_pnl_data()` for detail drill-down.
- Modify: `backend/services/data_service.py` — call the new fast path for summary endpoints; route detail to the existing path.

**Caveat**: This requires DBA coordination and access to the underlying tables behind the view. If they only expose the view, you can build the fact table on **your** SQL Server (a separate database we control) and ETL nightly via Python.

**Risk**: Aggregation is part of accounting logic territory — see [docs/CODING_PATTERNS.md](CODING_PATTERNS.md) "Accounting Logic — SACRED". The aggregation must produce identical totals to the existing transforms. Must be validated row-by-row against current outputs before cutover.

**Effort estimate**: 1–2 weeks including DBA coordination, validation, and rollback plan.

**Validation strategy**:
1. Deploy the new endpoint behind a feature flag.
2. For one full month, run **both** paths in parallel and diff the results.
3. Only cut over once diffs are zero across all 4 companies.

---

### 2.3 — Throttle per-request parallelism

**Why**: `fetch_max_workers=5` ([backend/config/settings.py:33](backend/config/settings.py#L33)) means each user request can launch up to 5 simultaneous queries. Counter-intuitively, when the DB is the bottleneck, **less parallelism is faster** because queries don't fight each other for shared resources. With 3 Gunicorn workers each spawning 5 threads, peak DB connections from a single page load can hit 15.

**What changes**:
- Lower `FETCH_MAX_WORKERS` to `2` in `.env`.
- Re-measure cold-load times; if they don't regress, ship it.

**Risk**: Cold loads serialize more, so they may take 1–2s longer for low-volume companies. For high-volume companies under contention they'll be faster.

**Effort**: 30 minutes.

---

### Tier 2 summary

After 2.1 + 2.3 (and ideally 2.2), the system can comfortably handle **30+ concurrent users on cached data** and **5–10 concurrent cold loads** without timeouts. Tier 2.2 is the architectural unlock that future-proofs the data layer.

---

## Tier 3 — Long-term platform work

### 3.1 — Coordinate with the DBA on indexes

**Why**: Even with caching, eventually a user hits a path that scans the view. If the underlying tables don't have a covering index, those queries will always be slow. See [docs/SQL_INDEX_RECOMMENDATIONS.md](SQL_INDEX_RECOMMENDATIONS.md) for the recommended index definition.

**Action items for the DBA**:
1. Confirm whether `(CIA, FECHA, CUENTA_CONTABLE)` is indexed on the underlying tables.
2. Check `sys.dm_db_missing_index_details` for suggestions.
3. Schedule a maintenance window to add the covering index.
4. Verify auto-stats are enabled on those tables.
5. Investigate whether the view itself can be **indexed** (materialized) — this is a SQL Server feature where the view's result set is persisted to disk and maintained automatically.

### 3.2 — Switch to async Gunicorn workers

**Why**: With sync workers, one slow request blocks the whole worker for the duration. With `gthread` (e.g., 4 threads × 3 workers = 12 concurrent requests), the worker can serve other users while one is waiting on the DB.

**What changes**:
- `backend/gunicorn.conf.py`: `worker_class = "gthread"`, `threads = 4`.
- Verify `pyodbc` connection handling is thread-safe under concurrent use (it is, but pool sizing may need adjustment — bump `DB_POOL_SIZE` to 16).
- Confirm the in-memory caches are still thread-safe (they use a single lock today; should be fine).

**Risk**: Threading bugs are subtle. Test thoroughly under load before promoting.

**Effort**: 2–3 days including load testing.

### 3.3 — Observability before the next failure

You only learned about the 2026-05-05 incident because the user reported it. By the time you investigated, the slow window had passed and you couldn't see what the SQL Server was doing.

**Add**:
- Prometheus / StatsD metrics on every DB fetch: duration, row count, company, success/fail.
- A Grafana panel showing p50/p95/p99 query times bucketed by company.
- An alert: "any query > 60s" → Slack / email.
- Optionally, request-level tracing via OpenTelemetry.

**Effort**: 1 week to set up, ongoing maintenance.

---

## Decision tree: how to choose what to do next

| Scenario | Do this |
|----------|---------|
| Failure happened today, need short-term fix | Tier 1.1 (5 min) |
| Failures recurring weekly | Tier 1 in full (1 day) |
| Multiple users, post-deploy failures common | Tier 1.2 + 1.3 (priority) |
| Adding more users, > 10 concurrent expected | Tier 2.1 (Redis) |
| FIBERLINE/FIBERTECH consistently slow even with cache | Tier 2.2 (fact table) + 3.1 (DBA index) |
| Want to scale past 30 users | Tier 3.2 (async workers) |
| Want to know problems before users report | Tier 3.3 (observability) |

---

## Appendix A — How to reproduce the failure for testing

After making any of these changes, reproduce the original 2026-05-05 conditions to verify the fix:

```bash
# From the FLXContabilidad directory, with venv activated
./venv/bin/python <<'PY'
import sys, os, time
sys.path.insert(0, 'backend'); sys.path.insert(0, 'backend/services')
from dotenv import load_dotenv
load_dotenv('.env')
from data.db import connect
from datetime import date
from concurrent.futures import ThreadPoolExecutor

def run(label, prefixes, start, end, cia='FIBERTECH'):
    sql = ("SELECT CIA, CUENTA_CONTABLE, DESCRIPCION, NIT, RAZON_SOCIAL, "
           "CENTRO_COSTO, DESC_CECO, FECHA, DEBITO_LOCAL, CREDITO_LOCAL, ASIENTO "
           "FROM REPORTES.VISTA_ANALISIS_CECOS "
           "WHERE CIA = ? AND FECHA >= ? AND FECHA < ? "
           "AND (" + " OR ".join("CUENTA_CONTABLE LIKE ?" for _ in prefixes) + ") "
           "AND FUENTE NOT LIKE 'CIERRE%'")
    params = [cia, start, end] + [f"{p}%" for p in prefixes]
    with connect() as c:
        cur = c.cursor()
        t0 = time.time()
        cur.execute(sql, params)
        n = sum(1 for _ in cur)
        return label, n, time.time() - t0

# Simulate 4 concurrent users on FIBERTECH (8 queries total)
jobs = []
for i in range(4):
    jobs.append((f"u{i} PNL", ('6','7','8'), date(2026,1,1), date(2027,1,1)))
    jobs.append((f"u{i} BS",  ('1','2','3','4','5'), date(2026,1,1), date(2026,5,1)))

with ThreadPoolExecutor(max_workers=8) as pool:
    for f in [pool.submit(run, *j) for j in jobs]:
        try:
            label, n, dt = f.result()
            mark = " ← OVER 120s" if dt > 120 else (" ← OVER 60s" if dt > 60 else "")
            print(f"{label}: {n:>7} rows in {dt:6.2f}s{mark}")
        except Exception as e:
            print("FAIL:", str(e)[:200])
PY
```

Expected behavior:
- **Before any fixes**: queries take 40–80s; some may hit `Query timeout expired`.
- **After Tier 1.1** (300s timeout): queries finish in 40–80s, no timeouts.
- **After Tier 1.2 + 1.3** (warmup + single-flight): only 2 unique queries actually run (the cache absorbs the rest); test should complete in ~5s.
- **After Tier 2.1** (Redis): same as above but consistent across workers.
- **After Tier 2.2** (fact table): summary queries finish in <1s regardless of concurrency.

---

## Appendix B — Files that will change

For each tier, here's the exact list of files modified or created. Use this as a checklist when reviewing PRs.

### Tier 1.1
- `.env`
- `.env.production` (if exists)

### Tier 1.2 — REVERTED (do not implement)
See post-mortem in the 1.2 section above. The files listed below were created and then removed on 2026-05-12 due to OOM.
- ~~New: `backend/services/warmup.py`~~ (reverted)
- ~~Modified: `backend/gunicorn.conf.py`~~ (reverted)

### Tier 1.3
- Modified: `backend/services/data_service.py` (single-flight locks)

### Tier 2.1
- New: `backend/services/cache_redis.py`
- Modified: `backend/services/data_service.py`
- Modified: `requirements.txt`
- Modified: `setup_infrastructure.sh`
- New: systemd unit for Redis

### Tier 2.2
- New: `nightly_build_FACT_MENSUAL.sql` (SQL Agent job)
- New: `REPORTES.FACT_ANALISIS_MENSUAL` table
- Modified: `backend/data/queries.py`
- Modified: `backend/services/data_service.py`

### Tier 2.3
- `.env`

### Tier 3.1
- Coordinate with DBA — see [docs/SQL_INDEX_RECOMMENDATIONS.md](SQL_INDEX_RECOMMENDATIONS.md).

### Tier 3.2
- `backend/gunicorn.conf.py`
- `.env` (DB_POOL_SIZE)

### Tier 3.3
- `backend/app.py` (metrics middleware)
- `backend/data/queries.py` (timing histograms)
- New: Grafana dashboard JSON
- New: alerting rules
