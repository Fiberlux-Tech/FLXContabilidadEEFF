"""Startup cache warmup — pre-fetch P&L + BS for all companies on boot.

After a deploy or systemd restart all in-memory caches are empty. The first
user to hit the dashboard triggers a synchronous DB fetch in their request
thread; if multiple users land simultaneously they each fire their own
queries, hitting the contention pattern that caused the 2026-05-05 outage.

This module warms the cache in a background thread immediately after a
gunicorn worker starts. An fcntl flock ensures exactly one worker across
the whole service is elected to do the work — the others see the lock is
held and bail out, relying on the disk cache the elected worker writes.

Warmup is serial across companies (not parallel) — concurrent warmup is
exactly the contention pattern we are trying to avoid.
"""

import fcntl
import logging
import threading
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("flxcontabilidad.warmup")

# Warm the 4 real companies first, CONSOLIDADO last. Consolidated views
# pull all 4 companies concurrently inside fetch_*_consolidated — if it
# times out under DB pressure, individual company views still work.
_COMPANIES = ("FIBERLINE", "FIBERLUX", "FIBERTECH", "NEXTNET", "CONSOLIDADO")

_LOCK_PATH = Path("/tmp/flx_warmup.lock")


def warmup_async() -> None:
    """Try to acquire the elector lock; if we get it, spawn the warmup thread.

    Called from gunicorn's post_worker_init hook so it runs once per worker
    after fork. The flock elects exactly one worker across the service.
    """
    try:
        fh = open(_LOCK_PATH, "w")
    except OSError as e:
        logger.warning("warmup: cannot open lockfile %s: %s", _LOCK_PATH, e)
        return

    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fh.close()
        logger.info("warmup: another worker holds the lock, skipping")
        return

    t = threading.Thread(
        target=_warmup_blocking, args=(fh,),
        name="cache-warmup", daemon=True,
    )
    t.start()


def _warmup_blocking(lockfile) -> None:
    """Run inside the background thread; warms one company at a time.

    Holds the flock for the duration so any sibling worker that calls
    warmup_async() while we are running sees BlockingIOError and bails.
    """
    try:
        # Imported lazily so app startup is not blocked on data_service init.
        from services.data_service import load_pl_data, load_bs_data

        year = datetime.now().year
        logger.info("warmup: starting for year %d", year)
        for company in _COMPANIES:
            _warm_one(company, year, load_pl_data, load_bs_data)
        logger.info("warmup: done for year %d", year)
    except Exception:
        logger.exception("warmup: aborted with unexpected error")
    finally:
        try:
            fcntl.flock(lockfile, fcntl.LOCK_UN)
        except OSError:
            pass
        lockfile.close()


def _warm_one(company: str, year: int, load_pl, load_bs) -> None:
    """Warm P&L then BS for one company. Failures are logged and swallowed."""
    try:
        logger.info("warmup: P&L %s/%d starting", company, year)
        load_pl(company, year)
        logger.info("warmup: P&L %s/%d done", company, year)
    except Exception as e:
        logger.warning("warmup: P&L %s/%d failed: %s", company, year, e)
        return  # if P&L fails, BS will fail too (BS depends on pl_df cache)

    try:
        logger.info("warmup: BS %s/%d starting", company, year)
        load_bs(company, year)
        logger.info("warmup: BS %s/%d done", company, year)
    except Exception as e:
        logger.warning("warmup: BS %s/%d failed: %s", company, year, e)
