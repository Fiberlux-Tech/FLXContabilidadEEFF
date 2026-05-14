"""Force a scheduler refresh cycle on demand.

Useful on staging, where the scheduler is disabled via FLX_DISABLE_SCHEDULER
and developers want fresh data for testing. Also useful on prod for ad-hoc
rebuilds outside the hourly cadence.

Reuses refresh_scheduler._refresh_cycle so the behavior is identical to
what the hourly scheduler does automatically — same invalidate, same
load_pl_data + load_bs_data, same fact-pickle build for real companies.

Usage (from the backend directory):
    ../venv/bin/python3 scripts/refresh_cache.py
    ../venv/bin/python3 scripts/refresh_cache.py --company FIBERLUX --year 2025

Exit code 0 on success, 1 if any cell fails.
"""

import argparse
import logging
import sys
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve()
BACKEND = HERE.parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "services"))

from services.data_service import (
    invalidate_cache, load_pl_data, load_bs_data,
    _caches, _build_fact, _save_to_disk,
)
from services.refresh_scheduler import _refresh_cycle
from config.company import CONSOLIDADO, COMPANY_META

logger = logging.getLogger("refresh_cache")


def _refresh_one(company: str, year: int) -> bool:
    """Refresh a single (company, year). Mirrors the per-cell body of
    refresh_scheduler._refresh_cycle. Returns True on success."""
    try:
        invalidate_cache(company, year)
        load_pl_data(company, year)
        load_bs_data(company, year)
        if company != CONSOLIDADO:
            df_stmt = _caches["pl_stmt"].get(company, year)
            if df_stmt is not None:
                fact = _build_fact(df_stmt)
                _save_to_disk(company, year, fact, kind="fact")
                logger.info("refresh: %s/%d fact pickle written (%d rows)",
                            company, year, len(fact))
        logger.info("refresh: %s/%d done", company, year)
        return True
    except Exception:
        logger.exception("refresh: %s/%d FAILED", company, year)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--company",
                        help="Single company (default: all in COMPANY_META)")
    parser.add_argument("--year", type=int,
                        help="Single year (default: previous and current)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # If neither filter is specified, delegate to the full _refresh_cycle so
    # we share its smallest-first ordering and try/except scaffolding.
    if not args.company and not args.year:
        now = datetime.now(ZoneInfo("America/Lima"))
        _refresh_cycle(
            now, invalidate_cache, load_pl_data, load_bs_data,
            _caches, _build_fact, _save_to_disk, CONSOLIDADO,
        )
        return 0

    # Narrow path: one or both filters specified.
    year_now = datetime.now(ZoneInfo("America/Lima")).year
    years = [args.year] if args.year else [year_now - 1, year_now]
    companies = [args.company] if args.company else list(COMPANY_META.keys())

    failures = 0
    for company in companies:
        for year in years:
            if not _refresh_one(company, year):
                failures += 1

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
