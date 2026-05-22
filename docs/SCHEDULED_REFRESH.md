# Scheduled Refresh

> **Status**: Design agreed 2026-05-12. Not yet implemented.
> **Owner**: Backend team.
> **Supersedes**: Phase 1 (Redis) and Phase 3 (gthread) in [SCALING_ROADMAP.md](SCALING_ROADMAP.md). See that doc's "Scope change 2026-05-12" section for the pivot rationale.
> **Last updated**: 2026-05-12.

## Why

The on-demand cache-fill model is the structural cause of the memory and latency pressure documented in [SCALING_ROADMAP.md](SCALING_ROADMAP.md): the first user to hit a cold `(company, year)` triggers a 30–60 s synchronous fetch in their request thread, and three workers can independently allocate the same ~600 MB DataFrame for the same company before the cross-process flock deduplicates them. Phase 1 of the roadmap was designed to fix this by moving the cache into Redis. Phase 1 is real engineering work — new dependency, new failure mode, new ops surface — and its win is mostly invisible to users who are already accustomed to "first click is slow."

The user confirmed that **one hour of data staleness on the summary path is acceptable** for the finance team's workflow. Given that constraint, a far simpler design is sufficient: a background thread refreshes the cache on a schedule, and user requests are guaranteed to hit warm disk caches (no DB queries fired on the summary path). No new dependency. No new failure mode visible to users (cold-cache concerns become a deploy-window concern, not a per-request concern). The architectural cost of the pivot is "the dashboard shows data that is up to 60 minutes old." The finance team has accepted that cost.

**What this design does NOT solve** (added 2026-05-14 after staging observation): the scheduler runs in one elected worker; the other 2 workers still pay a 5–15 second pickle-load cost the first time each `(company, year)` pair is requested on them. See "Known limitation" below. Phase 2 (fact table) shrinks pickles ~16× and effectively eliminates this remaining cost.

## Behavior

> **What users see**: every dashboard click hits a warm cache. No 30 s spinner on first load; no contention spikes when multiple users open the same view; no Refresh button. The dashboard footer should show "data as of HH:MM Lima" so users know how fresh the numbers are (see Risks below — surfacing this is part of the rollout).

Concretely, during a normal day:

| Time (Lima)  | What happens                                                                 |
|--------------|------------------------------------------------------------------------------|
| 08:00        | Scheduler fires. Walks 8 refresh units (4 companies × 2 years), serial, smallest first. Each unit: `invalidate_cache` → `load_pl_data` → `load_bs_data`. Cycle runs ~5–10 min (verify on staging). |
| 08:30        | First user lands. If they hit the elected worker, sub-second. If they hit one of the other 2 workers, they pay a pickle-load cost (5–15 s for the big companies — see "Known limitation" below). Either way, **no DB hit**. |
| 08:30–09:00  | Users click around. Each `(company, year)` × worker combination pays the pickle cost once, then is instant from then on. After ~10 min of organic browsing all 3 workers are fully warm. Drill-down to detail journal entries hits row-level cache (already populated by the scheduler via `load_pl_data` → `_ensure_pl_stmt_cached`). |
| 09:00        | Scheduler fires again. Re-invalidates and re-fetches. Active users transiently see a sub-second blip on their next click if they happen to land between `invalidate_cache` and the cache repopulation for the company they are viewing (see "Architecture" below for the ordering that minimizes this). |
| 10:00, 11:00, … 22:00 | Refresh cycles continue. 15 cycles per day total. |
| 22:00 – next 08:00 | Scheduler idle. Cache stays warm with the 22:00 snapshot for overnight viewing. After-hours users (rare) still hit fresh-enough data. |

**Cold start (post-deploy or post-restart)**: the gunicorn workers restart, the in-memory `_caches` dicts are empty, but the disk pickle cache at `backend/services/.stmt_cache/` survives — `_try_pl_stmt_from_disk` at [data_service.py:766](../backend/services/data_service.py#L766) rehydrates from disk. Two scenarios:

- **Restart during 08:00–22:00**: first user request after restart pays the pickle-load cost (5–15 s for FIBERLINE/FIBERTECH — observed on staging 2026-05-14), then the next scheduled cycle refreshes from the DB. No user ever triggers a DB fetch on the summary path.
- **Restart outside 08:00–22:00**: disk pickle is up to 10 hours old. First user gets the 22:00-previous-day snapshot until 08:00 fires. This is the same staleness window the user already accepted.

**No manual refresh.** The Refresh button at [frontend/src/features/dashboard/TopBar.tsx:278-280](../frontend/src/features/dashboard/TopBar.tsx#L278) is removed. The `force_refresh` field in API request bodies is ignored (see Implementation). Internal `force_refresh=True` callers inside `get_detail_records` at [data_service.py:1220](../backend/services/data_service.py#L1220) and [data_service.py:1230](../backend/services/data_service.py#L1230) stay — those are the drill-down fallback for when a user clicks into a row that is not yet in the row-level cache; they are not user-facing refresh buttons.

## Known limitation: per-worker pickle reload

> **The scheduler eliminates DB queries on user requests, but does not eliminate the per-worker pickle-load cost.** Observed on staging 2026-05-14: 5–15 seconds of pandas deserialization per cold worker per `(company, year)` for the largest companies (FIBERLINE, FIBERTECH).

We run 3 gunicorn workers (separate Python processes). Each worker has its own in-memory `_caches` dict. The scheduler runs in **one elected worker** and warms that worker's in-memory cache plus the shared on-disk pickles. The other 2 workers' in-memory caches remain empty until a user request lands on them.

When a request lands on a "cold" worker:
1. Worker checks `_caches["pl_stmt"][company, year]` → miss
2. Worker calls `_try_pl_stmt_from_disk` → loads the pickle (5–15 s for big companies)
3. Worker computes preaggs, populates its in-memory cache
4. Future requests on that worker for the same `(company, year)` are instant (~ms)

**User-visible impact:**
- After scheduler cycle, the first 1–5 users browsing each `(company, year)` pair pay ~5–15 s on their first click on each cold worker
- After ~10 minutes of organic browsing, all 3 workers have all 4 companies × 2 years warm in memory, and everything is sub-second for the rest of the day
- On worker restart (deploy or systemd auto-restart), the warming-up window repeats
- Worst case observed (cold worker, FIBERTECH trailing-12M, both years): ~30 s total wait spread across pickle loads for `df_stmt`, `preagg`, `preagg_ex_ic`, `preagg_only_ic`, then prev-year repeat

**Why this remains after the scheduler:**
The scheduler shares state **across cycles within one worker**, not across workers within one cycle. The cross-worker deduplication that Phase 1 (Redis) was designed to provide is what would eliminate this. We deferred Phase 1 in favor of the scheduler because the scheduler removes the *DB* cost (much bigger than the pickle-load cost), and the user accepted hourly staleness as a tradeoff against complexity. The pickle-load cost was understood at design time but its magnitude (15s for the big companies, not 2–5s) was confirmed only on the 2026-05-14 staging deploy.

**Phase 2 (monthly fact table) makes this limitation disappear.** A 157 MB FIBERLINE_2025 pickle becomes ~10 MB after Phase 2. Pickle load time drops from ~10 s to <1 s, well below user-noticeable. Phase 2 is the natural next move; see [SCALING_ROADMAP.md](SCALING_ROADMAP.md) "Phase 2".

**Mitigations available today without Phase 2:**
- Encourage users to keep their dashboard tab open. The first click on each company warms that worker; subsequent clicks are instant on the same worker.
- Reduce gunicorn worker count to 1 (would eliminate the duplication entirely, at the cost of concurrent-request capacity — not recommended without measuring).
- Switch to `gthread` worker class (was deferred Phase 3; threads in the same process share the cache). Requires verifying thread safety end-to-end; held until Phase 1 or Phase 2 lands per the original roadmap.

## Architecture

Three pieces:

1. **Scheduler thread** — one daemon thread per worker process, started from `create_app()`. Sleeps until the next top-of-the-hour boundary, wakes up, checks the time-of-day gate, runs the refresh cycle, sleeps again. Uses stdlib only (`threading`, `time`, `datetime`, `zoneinfo`). No APScheduler, no cron, no new dependency.
2. **Elector** — `fcntl.flock` on `/tmp/flx_refresh.lock`, copying the pattern from the reverted `backend/services/warmup.py` (originally shipped in commit `901da34`, reverted in `ae42e3b`; the elector pattern was sound, only the at-boot timing was wrong). Each worker tries to acquire the lock at start; whichever wins runs the scheduler, the other two no-op. The lock is held for the lifetime of the worker, not per-cycle, so re-election only happens on worker restart.
3. **Refresh loop** — for each `(company, year)` in a deterministic smallest-first order, run `invalidate_cache(company, year)` then `load_pl_data(company, year)` then `load_bs_data(company, year)`, serially, with per-unit try/except so a failure on one company does not abort the rest.

> **Why elect at the worker level and not from gunicorn's `post_worker_init`?** The reverted warmup elected from `post_worker_init` and ran once at boot. The scheduler runs continuously and re-elects on every worker restart; doing it from `create_app()` keeps the lifecycle tied to the Flask app instance, which is the same lifecycle the `mem_monitor` daemon already uses (see [mem_monitor.py](../backend/services/mem_monitor.py)). One consistent pattern, not two.

> **Why serial, not parallel?** The 2026-05-12 warmup OOM. Parallel refresh of all companies holds ~1.5–2 GB of pandas state simultaneously, which exceeds the 5.8 GB box's safe working set once OS + workers are accounted for. Serial refresh keeps the transient memory at one company × two years ≈ 500–800 MB (verify on staging). Even with the Phase 0 cgroup ceiling, "slow and survives" beats "fast and OOMs."

> **Why invalidate-then-fetch, not fetch-then-swap?** Invalidating first frees the old DataFrame's memory before the new fetch allocates. Doing it in the opposite order would briefly hold *both* versions, doubling peak memory. The cost of the chosen ordering is a brief cache-miss window if a user request lands between the invalidate and the repopulation for that company — those users see a one-off ~2–5 s latency for the disk reload (the disk pickle is invalidated too, so they wait for the DB fetch the scheduler is mid-flight on). This is rare and acceptable.

### Company order

Smallest first to minimise the cumulative in-memory peak during the refresh cycle. From the verified pickle sizes:

| Order | Company    | df_stmt 2025 | df_stmt 2026 | Cumulative transient peak |
|-------|------------|--------------|--------------|---------------------------|
| 1     | FIBERLUX   | 13 MB        | 2.2 MB       | tiny                      |
| 2     | NEXTNET    | 9.1 MB       | 2.7 MB       | tiny                      |
| 3     | FIBERTECH  | 80 MB        | 29 MB        | ~250 MB in-memory         |
| 4     | FIBERLINE  | 157 MB       | 50 MB        | ~500 MB in-memory         |

Rationale: if the cycle fails partway, the smaller companies have already been refreshed; users of any individual company still see fresh data, with worst-case staleness on the largest company.

## Implementation

File-by-file.

### New file: `backend/services/refresh_scheduler.py`

Approximately 80–110 lines. Mirrors the structure of [mem_monitor.py](../backend/services/mem_monitor.py) (`start()` function, `_started` guard, daemon thread). Skeleton:

```python
"""Hourly cache refresh.

One elected worker runs a daemon thread that, every hour on the hour
between 8am and 10pm Lima time, walks all (company, year) pairs and
refreshes the cache. Other workers' calls to start() see the flock
held and no-op.

See docs/SCHEDULED_REFRESH.md for the design rationale.
"""

import fcntl
import logging
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger("flxcontabilidad.refresh_scheduler")

_TZ = ZoneInfo("America/Lima")
_LOCK_PATH = Path("/tmp/flx_refresh.lock")
_REFRESH_HOURS = range(8, 23)   # 8,9,...,22 → cycles fire at 08:00..22:00

# Smallest-first. See "Company order" in the doc.
_COMPANIES = ("FIBERLUX", "NEXTNET", "FIBERTECH", "FIBERLINE")

_started = False
_start_lock = threading.Lock()


def start() -> None:
    """Start the scheduler thread in this worker if we win the elector."""
    global _started
    with _start_lock:
        if _started:
            return
        fh = _try_acquire_lock()
        if fh is None:
            logger.info("refresh_scheduler: another worker holds the lock, skipping")
            _started = True   # don't retry on subsequent calls
            return
        t = threading.Thread(target=_run, args=(fh,),
                             name="refresh-scheduler", daemon=True)
        t.start()
        _started = True
        logger.info("refresh_scheduler: elected, thread started")


def _try_acquire_lock():
    try:
        fh = open(_LOCK_PATH, "w")
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fh
    except (OSError, BlockingIOError):
        return None


def _run(lockfile) -> None:
    # Imported lazily so worker boot is not blocked on data_service import.
    from services.data_service import (
        invalidate_cache, load_pl_data, load_bs_data,
    )
    try:
        while True:
            sleep_sec = _seconds_until_next_cycle(datetime.now(_TZ))
            time.sleep(sleep_sec)
            now = datetime.now(_TZ)
            if now.hour not in _REFRESH_HOURS:
                continue
            _refresh_cycle(now, invalidate_cache, load_pl_data, load_bs_data)
    except Exception:
        logger.exception("refresh_scheduler: thread crashed")
        # Do not release the lock — re-election only on worker restart.
        # A surviving crashed scheduler is the worst-case risk; see Risks.
```

The cycle body and sleep math are written out in the actual implementation; this skeleton captures the structure. Boundary tests for `_seconds_until_next_cycle` (verified 2026-05-14 against the actual implementation):
- 07:59 → 60 s (next fire 08:00)
- 08:00 → 3600 s (next fire 09:00)
- 22:00 → ~10 h (next fire is tomorrow 08:00; today 23:00 is outside the window)
- 23:00 → ~9 h
- 03:00 → ~5 h

Lima does **not** observe DST, which removes one whole class of bug. `zoneinfo` is stdlib since Python 3.9; verified Python 3.12 on the staging box.

### Edit: `backend/app.py`

Add three lines immediately after the `mem_monitor` start at [app.py:127-128](../backend/app.py#L127), inside `create_app()` and before `return app`:

```python
# Scheduled refresh (see docs/SCHEDULED_REFRESH.md)
from services.refresh_scheduler import start as _start_refresh
_start_refresh()
```

No other change to `app.py`.

### Edit: `backend/routes.py`

Two surgical edits:

- [routes.py:131](../backend/routes.py#L131) — currently `force_refresh = body.get('force_refresh', False)`. Delete that line and the `force_refresh=force_refresh` kwarg from the `service_fn(...)` call on line 133.
- [routes.py:198](../backend/routes.py#L198) — currently `force_refresh = body.get('force_refresh', False)`. Delete that line and the `force_refresh=force_refresh` kwarg from the `load_pl_section(...)` call on line 212.

Also drop the `Optional: { "force_refresh": true }` docstring lines at routes.py:148, 162, 174. The body field is silently ignored if any old client (or someone using curl) still sends it; that is the right backward-compat posture.

### Edit: `backend/services/data_service.py`

**Do not edit** the `force_refresh` kwarg on `_ensure_pl_stmt_cached`, `load_pl_data`, `load_bs_data`, `load_pl_section`. The internal callers at [data_service.py:1220](../backend/services/data_service.py#L1220) and [data_service.py:1230](../backend/services/data_service.py#L1230) use it for the drill-down fallback when row-level data is missing.

Keep `invalidate_cache` as is. The scheduler calls it. Keep the single-flight locks; they still serve the drill-down path.

### Frontend

Remove the Refresh button at [frontend/src/features/dashboard/TopBar.tsx:278-280](../frontend/src/features/dashboard/TopBar.tsx#L278):

```tsx
{/* Refresh */}
<button ... onClick={() => loadData(true)}>...</button>
```

And remove the `force_refresh: force` fields in [frontend/src/contexts/ReportContext.tsx:297, 305, 327, 335](../frontend/src/contexts/ReportContext.tsx#L297). The `force` parameter of `loadData` and `fetchBsData` becomes unused — drop it from those callbacks too. The auto-load behavior on `selectedCompany` / `selectedYear` change remains; users who switch companies still get fresh-from-cache data immediately.

## What NOT to do

Lessons from the 2026-05-12 warmup OOM, restated for the scheduler:

- **Never refresh companies in parallel.** Same OOM pattern. The transient memory advantage of serial is precisely the safety margin the box has.
- **Never hold all companies in memory simultaneously to "compare deltas" or "warm them all together."** The `invalidate_cache` → `load_pl_data` → `load_bs_data` cycle is per-company-per-year for a reason: one unit's DataFrames must be released before the next unit allocates.
- **Do not try to be clever with "refresh in the background while users are active."** The serial cost is the cost. A 5–10 min cycle running in one daemon thread is fine; squeezing it down by interleaving with user requests reintroduces the OOM risk.
- **Do not pull in APScheduler, Celery, or cron.** Stdlib `threading` + `time.sleep` + `zoneinfo` is enough. Adding a scheduler library means another dependency to upgrade, another failure mode to debug.
- **Do not move the elector to a Redis `SET NX EX`.** Redis is not installed; that was Phase 1's premise. `fcntl.flock` is what we have and what already works on this host.
- **Do not warmup at boot.** That was the reverted warmup's mistake. The scheduler's first cycle is governed by `_seconds_until_next_cycle` and will not fire until the next 8am–10pm top-of-the-hour. Cold-start service-from-disk-pickle is the contract.

## Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| **Scheduler thread dies silently**; cache goes stale for hours/days, finance team eventually notices the dashboard date is yesterday's. | Low to medium | High | (a) `_run` wraps the loop in `try/except` and logs `exception` on crash. (b) `mem_monitor` log lines continue regardless and act as a heartbeat — if the worker is alive, it logs every 300 s. (c) Surface a `last_refresh_at` timestamp via an admin endpoint and in the dashboard footer (see "Validation criteria" below); a missing/stale timestamp is the user-visible signal. |
| **Refresh cycle OOMs on the largest company** (the same scenario that killed warmup). | Low (with smallest-first ordering and Phase 0 cgroup ceiling) | Medium | Smallest-first order ensures the smaller companies are already fresh when the largest is attempted. `MemoryHigh=4G` triggers cgroup reclaim before the kernel OOM-killer. `FETCH_MAX_WORKERS=2` keeps the per-fetch parallel fan-out from doubling memory inside one fetch. |
| **Elector flock leaks** if the elected worker is killed -9. | Low | Low | `fcntl.flock` is held by the file descriptor; when the process dies, the kernel releases the lock. The next worker's `start()` call (after restart) re-elects. No manual cleanup needed. |
| **Time-of-day gate math wrong** (off-by-one on the 22:00 boundary, wrong year-rollover). | Medium pre-shipping, low after one cycle of soak | Medium | Unit-test `_seconds_until_next_cycle` with the boundary cases listed in the skeleton above before shipping. Lima does **not** observe DST. |
| **Disk pickles grow during the year and exceed the disk cache budget.** | Low | Low | Current total ~700 MB across 10 pickles; even tripling that is well under the host's free disk. `mem_monitor` doesn't measure disk; spot-check `du -sh backend/services/.stmt_cache/` after the first week. |
| **Refresh fires while a user is mid-drill-down** and clobbers their row-level cache. | Low | Low | `invalidate_cache` clears the per-`(company, year)` entry; the user's next click rehydrates from the just-written disk pickle. Sub-second blip, not a failure. |
| **Logging volume grows** (15 cycles × 4 companies × 2 years × 2 statements × multiple log lines per fetch). | Medium | Low | Existing log rotation at `backend/logs/error.log` should absorb it; verify rotation policy before shipping. If too noisy, tune the `_refresh_cycle` log to a single line per company-year pair. |

## Phase 0 interaction

All Phase 0 work stays. Specifically:

- The three commits already on `dev` (`c36d557` `mem_monitor`, `807d539` LRU caps to 6, `f17ea04` `FETCH_MAX_WORKERS` template default 5 → 2) ship as planned.
- The pending `.env` edit (`FETCH_MAX_WORKERS=2`) and the systemd edit (`MemoryHigh=4G` / `MemoryMax=5G`) still need to happen on staging. Sequence: do those *before* deploying the scheduler so the cgroup ceiling is in place the first time the scheduler holds a large company's DataFrame.
- The cache size caps (`max_entries=6` on heavy buckets) interact cleanly with the scheduler: 8 cells × 6-entry cap = the LRU never evicts the live set, but a runaway scheduler that somehow tried to hold all 4 companies × 2 years simultaneously in `pl_stmt` would still be bounded.
- The `mem_monitor` log is the only visibility into whether the scheduler is misbehaving. Do not skip it.

## Validation criteria

Scriptable, in order of how soon they need to pass.

1. **Scheduler is elected exactly once.** After service restart on staging, `grep "refresh_scheduler: elected" backend/logs/error.log` returns exactly one line; `grep "refresh_scheduler: another worker"` returns exactly two (the non-elected workers).
2. **First cycle fires at the next 8am–10pm top-of-the-hour.** After restart, no DB fetch logs (`grep "P&L fetch"`) appear until the next on-the-hour timestamp; then a burst of fetches over ~5–10 min, then silence until the next hour.
3. **All 8 units complete in one cycle.** Per cycle, the log shows exactly 8 `refresh: <COMPANY>/<YEAR> done` lines (or a mix of `done` and `FAILED` with the failure logged via `exception`). Cycle ends with `refresh: cycle complete`.
4. **User requests fire no DB queries during 8am–10pm steady state.** After one full cycle, exercise the dashboard for 10 min (4 companies, both years, drill into a few details). `grep -c "P&L fetch" backend/logs/error.log` should not increment during that window (drill-down may increment it if the user lands on an uncached partida — expected, covered by the kept internal `force_refresh=True` callers).
5. **No OOM during refresh.** After 24 h of soak, `journalctl -u flxcontabilidad-staging | grep -i "killed\|oom"` returns nothing. `mem_monitor` log shows `sys_available` never below 800 MB.
6. **Last-refresh visibility.** (Recommended additional work, not blocking.) Add an admin endpoint `/api/admin/refresh-status` returning `{ "last_cycle_complete": "2026-05-13T15:00:42-05:00", "elected_pid": 12345, "next_cycle_at": "2026-05-13T16:00:00-05:00" }`. The scheduler writes its own state into a module-level dict; the endpoint reads it. Track this as a follow-up commit if not in the initial PR.

## Rollout sequence

1. **Land the remaining Phase 0 ops steps on staging** (`.env` edit, systemd edit, `daemon-reload`, restart). Confirm `mem_monitor` is logging. **Do not skip this** — the cgroup ceiling is the safety net for step 4 below.
2. **Commit the scheduler + `app.py` + `routes.py` + frontend changes on `dev`.** Suggested commit message subject: `feat(refresh): hourly scheduled cache refresh (supersedes Phase 1)`. Two commits is fine: backend, then frontend Refresh-button removal.
3. **Push and `./deploy.sh` from the staging tree.**
4. **Watch for at least one full cycle inside the 8am–10pm window.** `tail -f backend/logs/error.log | grep refresh` should show `refresh: cycle starting`, eight `refresh: <COMPANY>/<YEAR> done` lines over ~5–10 min, and `refresh: cycle complete`.
5. **Run the dashboard manually for ~10 min after the cycle completes.** Verify no `P&L fetch` log lines appear from user requests.
6. **Soak for 24 h.** Tail `error.log` once per hour to confirm each cycle runs cleanly. Spot-check `mem_monitor` lines for memory regressions.
7. **Promote to prod** via `./promote.sh` from the prod tree, then apply the same `.env` + systemd edits on prod manually.
8. **After the first prod cycle**, repeat the user-request-fires-no-DB verification on prod.

## Sequencing with what's left of SCALING_ROADMAP

| Item | Where it lives | Status |
|------|----------------|--------|
| Phase 0 commits (mem_monitor, cache caps, FETCH_MAX_WORKERS) | `dev` branch, commits `c36d557` `807d539` `f17ea04` | Ready to deploy. |
| Phase 0 `.env` edit (`FETCH_MAX_WORKERS=2`) on staging + prod | Manual ops | Pending, do before scheduler ships. |
| Phase 0 systemd edit (`MemoryHigh=4G` / `MemoryMax=5G`) on staging + prod | Manual ops | Pending, do before scheduler ships. |
| **Scheduled refresh (this doc)** | New code on `dev` | **Next** after Phase 0 ops steps land. |
| Phase 2 (monthly fact pickles) | New code on `dev` (extends this scheduler) | Queued. Shrinks the cached `df_stmt` ~16× and closes the per-worker pickle-load limitation. No DBA dependency; see [FACT_TABLE.md](FACT_TABLE.md). |
| Phase 1 (Redis) | [SCALING_ROADMAP.md](SCALING_ROADMAP.md) Phase 1 | Deferred indefinitely. |
| Phase 3 (gthread workers) | [SCALING_ROADMAP.md](SCALING_ROADMAP.md) Phase 3 | Deferred. |
| Phase 4 (DBA index) | [SQL_INDEX_RECOMMENDATIONS.md](SQL_INDEX_RECOMMENDATIONS.md) | Unblocked, gated on DBA only. |

## What this doc is not

This is not a plan to remove the disk pickle cache. The disk cache is the durable layer that survives restarts and bridges the gap between the 22:00 cycle and the next 08:00 cycle. It stays.

This is not a plan to remove single-flight locking. Drill-down still hits the row-level path, which still needs `_get_inflight_lock` and `_CrossProcLock` to coalesce simultaneous DB hits.

This is not a long-term commitment to "no Redis ever." If finance team feedback later flags the 60-min staleness as too coarse — or if a real-time view of intraday journal entries becomes a requirement — Phase 1 stays on the shelf as the next architectural unlock. The scheduler is the simplest thing that works for the requirements as they stand today.
