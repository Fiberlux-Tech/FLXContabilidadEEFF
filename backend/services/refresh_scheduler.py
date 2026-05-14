"""Hourly cache refresh.

One elected worker runs a daemon thread that, every hour on the hour
between 8am and 10pm Lima time, walks all (company, year) pairs and
refreshes the cache. Other workers' calls to start() see the flock
held and no-op.

User requests are served exclusively from the warmed disk/in-memory
caches. No user request triggers a DB fetch on the summary path.

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

# Cycles fire at 08:00, 09:00, ..., 22:00 inclusive. 15 cycles per day.
# Aligned with the finance team's working hours.
_REFRESH_HOURS = range(8, 23)

# Smallest-first; CONSOLIDADO last. See "Company order" in the doc.
# If CONSOLIDADO refresh fails, the 4 real companies are already fresh.
_COMPANIES = ("FIBERLUX", "NEXTNET", "FIBERTECH", "FIBERLINE", "CONSOLIDADO")

# Module-level state for visibility (read by admin endpoint if added later).
_last_cycle_complete_at: datetime | None = None
_last_cycle_failures: list[str] = []

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
        logger.info("refresh_scheduler: elected, thread started (hours=%s)",
                    list(_REFRESH_HOURS))


def _try_acquire_lock():
    try:
        fh = open(_LOCK_PATH, "w")
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fh
    except (OSError, BlockingIOError):
        return None


def _seconds_until_next_cycle(now: datetime) -> float:
    """Sleep target = next top-of-the-hour that lies inside _REFRESH_HOURS.

    Examples (with _REFRESH_HOURS = 8..22):
      now=07:59  -> ~1s   (next fire = today 08:00)
      now=08:00  -> ~3600 (next fire = today 09:00)
      now=22:00  -> ~36000 (next fire = tomorrow 08:00; today 23:00 is outside window)
      now=23:00  -> ~32400 (next fire = tomorrow 08:00)
      now=03:00  -> ~18000 (next fire = today 08:00)
    """
    nxt = (now.replace(minute=0, second=0, microsecond=0)
           + timedelta(hours=1))
    if nxt.hour not in _REFRESH_HOURS:
        # We've passed the last cycle of the day (or it's the middle of the night).
        # Target 08:00 of the next eligible day.
        target_day = nxt.date()
        if nxt.hour >= max(_REFRESH_HOURS) + 1:
            target_day = target_day + timedelta(days=1)
        nxt = datetime(target_day.year, target_day.month, target_day.day,
                       hour=min(_REFRESH_HOURS), tzinfo=_TZ)
    return max(1.0, (nxt - now).total_seconds())


def _run(lockfile) -> None:
    # Imported lazily so worker boot is not blocked on data_service import,
    # and so circular-import risk is avoided.
    from services.data_service import (
        invalidate_cache, load_pl_data, load_bs_data,
    )
    try:
        while True:
            now = datetime.now(_TZ)
            sleep_sec = _seconds_until_next_cycle(now)
            logger.info("refresh_scheduler: sleeping %.0fs until next cycle", sleep_sec)
            time.sleep(sleep_sec)
            now = datetime.now(_TZ)
            if now.hour not in _REFRESH_HOURS:
                # Defensive: in case sleep returned early or DST drift (Lima
                # doesn't observe DST, but cheap to check).
                continue
            _refresh_cycle(now, invalidate_cache, load_pl_data, load_bs_data)
    except Exception:
        logger.exception("refresh_scheduler: thread crashed; lock retained")
        # Do not release the lock — re-election only on worker restart.
        # A surviving crashed scheduler is the worst-case risk; see
        # docs/SCHEDULED_REFRESH.md Risks section.


def _refresh_cycle(start_at: datetime, invalidate_cache, load_pl_data, load_bs_data) -> None:
    global _last_cycle_complete_at, _last_cycle_failures
    year_now = start_at.year
    years = (year_now - 1, year_now)
    failures: list[str] = []
    logger.info("refresh: cycle starting at %s, years=%s", start_at.isoformat(), years)
    t0 = time.perf_counter()
    for company in _COMPANIES:
        for year in years:
            try:
                invalidate_cache(company, year)
                load_pl_data(company, year)
                load_bs_data(company, year)
                logger.info("refresh: %s/%d done", company, year)
            except Exception as e:
                failures.append(f"{company}/{year}: {e}")
                logger.exception("refresh: %s/%d FAILED", company, year)
    _last_cycle_complete_at = datetime.now(_TZ)
    _last_cycle_failures = failures
    logger.info(
        "refresh: cycle complete in %.1fs (failures=%d)",
        time.perf_counter() - t0, len(failures),
    )


def get_status() -> dict:
    """Snapshot of scheduler state for admin endpoints / health checks."""
    return {
        "elected": _started and _last_cycle_complete_at is not None or _try_check_lock_held(),
        "last_cycle_complete_at": (
            _last_cycle_complete_at.isoformat() if _last_cycle_complete_at else None
        ),
        "last_cycle_failures": list(_last_cycle_failures),
        "refresh_hours": list(_REFRESH_HOURS),
        "companies": list(_COMPANIES),
    }


def _try_check_lock_held() -> bool:
    """True if this process is holding the elector lock."""
    # Simple heuristic; the real signal is the _last_cycle_complete_at timestamp.
    return _LOCK_PATH.exists()
