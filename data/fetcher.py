"""Data fetching — concurrent DB queries with previous-year caching."""

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

from data.db import connect
from data.queries import fetch_pnl_data, fetch_bs_data
from config.calendar import MIN_YEAR


logger = logging.getLogger("plantillas.data_fetcher")

CACHE_DIR = Path(__file__).parent / ".cache"
# Previous-year data is historical/immutable; 30 days is a safe TTL that
# avoids serving stale files while preventing unnecessary DB round-trips.
CACHE_TTL_SECONDS = 30 * 24 * 3600


def _cache_path(company: str, year: int, data_type: str) -> Path:
    """Return the cache file path for previous-year data.

    data_type: 'pnl' or 'bs'
    """
    return CACHE_DIR / f"{data_type}_{company}_{year}.csv"


def _load_cached(company: str, year: int, data_type: str) -> pd.DataFrame | None:
    """Load cached previous-year data if available and not expired."""
    path = _cache_path(company, year, data_type)
    if path.exists():
        age = time.time() - path.stat().st_mtime
        if age > CACHE_TTL_SECONDS:
            logger.info("Cache expired (%.0f days), will re-fetch: %s", age / 86400, path.name)
            path.unlink(missing_ok=True)
            return None
        try:
            df = pd.read_csv(path)
            logger.info("Loaded cached %s data: %s", data_type.upper(), path.name)
            return df
        except (OSError, ValueError, Exception):
            logger.warning("Cache file corrupted, will re-fetch: %s", path.name)
    return None


def _save_cache(company: str, year: int, data_type: str, df: pd.DataFrame) -> None:
    """Persist previous-year data to a file-based cache."""
    CACHE_DIR.mkdir(exist_ok=True)
    path = _cache_path(company, year, data_type)
    try:
        df.to_csv(path, index=False)
        logger.info("Cached %s data to %s", data_type.upper(), path.name)
    except OSError:
        logger.warning("Failed to write cache file: %s", path.name)


def _fetch_with_own_conn(fetch_fn, conn_factory, *args, **kwargs) -> pd.DataFrame:
    """Run *fetch_fn* using its own database connection (thread-safe)."""
    with conn_factory() as conn:
        return fetch_fn(conn, *args, **kwargs)


def fetch_all_data(company: str, year: int, month: int | None, conn_factory=None, *, need_pdf: bool = True) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Connect to DB and fetch raw DataFrames for Excel and PDF.

    Independent queries run concurrently via ThreadPoolExecutor, each with
    its own connection (pyodbc connections are not thread-safe).

    When *need_pdf* is False, PDF-only queries (full-year P&L, previous-year
    P&L, previous-year BS) are skipped, returning empty DataFrames instead.

    Returns (raw, raw_current_full, raw_prev, raw_bs, raw_bs_prev).
    """
    if conn_factory is None:
        conn_factory = connect

    prev_year = year - 1

    # Check cache before submitting threads for prev-year data
    cached_prev_pnl = None
    cached_prev_bs = None
    if need_pdf and prev_year >= MIN_YEAR:
        cached_prev_pnl = _load_cached(company, prev_year, "pnl")
        cached_prev_bs = _load_cached(company, prev_year, "bs")

    logger.info("Fetching data concurrently%s...", "" if need_pdf else " (Excel-only)")
    futures = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        # 1) P&L full year (always fetch full year; filter in-memory for month)
        futures["raw_full"] = pool.submit(_fetch_with_own_conn, fetch_pnl_data, conn_factory, company, year, None)

        # 2) P&L previous year — only needed for PDF (skip if cached or not applicable)
        if need_pdf and prev_year >= MIN_YEAR and cached_prev_pnl is None:
            futures["raw_prev"] = pool.submit(_fetch_with_own_conn, fetch_pnl_data, conn_factory, company, prev_year, None)

        # 3) BS current (always needed for Excel BS sheets)
        futures["raw_bs"] = pool.submit(_fetch_with_own_conn, fetch_bs_data, conn_factory, company, year, month)

        # 4) BS previous year — only needed for PDF (skip if cached)
        if need_pdf and prev_year >= MIN_YEAR and cached_prev_bs is None:
            futures["raw_bs_prev"] = pool.submit(_fetch_with_own_conn, fetch_bs_data, conn_factory, company, prev_year, month)

    # Collect results (raises on first query error)
    results = {name: fut.result() for name, fut in futures.items()}

    raw_current_full = results["raw_full"]
    # Filter to specific month in-memory (same date range logic as the SQL query)
    if month is not None:
        start = pd.Timestamp(year, month, 1)
        end = pd.Timestamp(year + 1, 1, 1) if month == 12 else pd.Timestamp(year, month + 1, 1)
        raw = raw_current_full[(raw_current_full["FECHA"] >= start) & (raw_current_full["FECHA"] < end)].copy()
    else:
        raw = raw_current_full

    if need_pdf and prev_year >= MIN_YEAR:
        if cached_prev_pnl is not None:
            raw_prev = cached_prev_pnl
        else:
            raw_prev = results["raw_prev"]
            _save_cache(company, prev_year, "pnl", raw_prev)
    elif prev_year >= MIN_YEAR:
        raw_prev = pd.DataFrame(columns=raw.columns)
    else:
        logger.info("Previous year %d < 2025; using zeros for comparison.", prev_year)
        raw_prev = pd.DataFrame(columns=raw.columns)

    raw_bs = results["raw_bs"]

    if need_pdf and prev_year >= MIN_YEAR:
        if cached_prev_bs is not None:
            raw_bs_prev = cached_prev_bs
        else:
            raw_bs_prev = results["raw_bs_prev"]
            _save_cache(company, prev_year, "bs", raw_bs_prev)
    else:
        if not need_pdf:
            raw_bs_prev = pd.DataFrame(columns=raw_bs.columns if not raw_bs.empty else raw.columns)
        else:
            logger.info("Previous year %d < 2025; using empty BS for comparison.", prev_year)
            raw_bs_prev = pd.DataFrame(columns=raw_bs.columns if not raw_bs.empty else raw.columns)

    return raw, raw_current_full, raw_prev, raw_bs, raw_bs_prev
