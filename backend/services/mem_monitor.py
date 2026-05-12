"""Per-worker memory monitor.

Runs as a daemon thread inside each gunicorn worker (started from
backend/app.py's create_app() factory after fork). Logs system-wide memory
plus this worker's RSS every 300 s to the 'flxcontabilidad.mem_monitor'
logger, which inherits the basicConfig at app.py:46.

Phase 0 deliverable per docs/SCALING_ROADMAP.md — pure observability, no
behavior change. Mirrors the daemon-thread pattern at
data_service.py:1083-1106 (_prefetch_bs_background).
"""

import logging
import os
import threading
import time

import psutil

logger = logging.getLogger("flxcontabilidad.mem_monitor")

_INTERVAL_SEC = 300
_started = False
_start_lock = threading.Lock()


def _worker() -> None:
    proc = psutil.Process()
    pid = os.getpid()
    while True:
        try:
            vm = psutil.virtual_memory()
            rss_mb = proc.memory_info().rss / (1024 * 1024)
            logger.info(
                "pid=%d rss=%.1fMB sys_total=%.1fGB sys_available=%.1fGB sys_percent=%.1f",
                pid,
                rss_mb,
                vm.total / (1024 ** 3),
                vm.available / (1024 ** 3),
                vm.percent,
            )
        except Exception:
            logger.exception("mem_monitor sample failed")
        time.sleep(_INTERVAL_SEC)


def start() -> None:
    """Start the monitor thread once per process. Safe to call repeatedly."""
    global _started
    with _start_lock:
        if _started:
            return
        t = threading.Thread(target=_worker, name="mem_monitor", daemon=True)
        t.start()
        _started = True
        logger.info("mem_monitor started (interval=%ds)", _INTERVAL_SEC)
