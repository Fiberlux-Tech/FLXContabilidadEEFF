"""Data fetching — concurrent DB queries for the dashboard."""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

import pandas as pd

from data.db import connect
from data.queries import (
    fetch_pnl_data, fetch_bs_data,
    fetch_pnl_summary, fetch_bs_summary,
    fetch_pnl_detail, fetch_pnl_detail_count,
    fetch_bs_detail, fetch_bs_detail_count,
)
from config.period import month_end_boundary
from config.settings import get_config


logger = logging.getLogger("plantillas.data_fetcher")


def _fetch_with_own_conn(fetch_fn, conn_factory, *args, **kwargs) -> pd.DataFrame:
    """Run *fetch_fn* using its own database connection (thread-safe)."""
    with conn_factory() as conn:
        return fetch_fn(conn, *args, **kwargs)


def fetch_all_data(company: str, year: int, month: int | None, conn_factory=None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Connect to DB and fetch the dashboard's raw P&L + BS DataFrames concurrently.

    Each query runs on its own connection (pyodbc connections are not thread-safe).

    Returns (raw_current_full, raw_bs) — both filtered to the eligible/statement
    subset by the underlying SQL views.
    """
    if conn_factory is None:
        conn_factory = connect

    logger.info("Fetching data concurrently...")
    max_workers = get_config().db.fetch_max_workers
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            "raw_full": pool.submit(
                _fetch_with_own_conn, fetch_pnl_data, conn_factory,
                company, year, None,
            ),
            "raw_bs": pool.submit(
                _fetch_with_own_conn, fetch_bs_data, conn_factory,
                company, year, month,
            ),
        }

    # Per-query timeout prevents hung DB connections from blocking. Add slack
    # over pyodbc's conn.timeout so HYT00 fires first with a real SQL error
    # instead of the executor wrapping it in a generic FuturesTimeoutError.
    per_query_timeout = get_config().db.query_timeout + 30
    results = {}
    for name, fut in futures.items():
        try:
            t_wait = time.perf_counter()
            results[name] = fut.result(timeout=per_query_timeout)
            logger.info("Query '%s': %.2fs, %d rows", name, time.perf_counter() - t_wait, len(results[name]))
        except FuturesTimeoutError:
            raise RuntimeError(f"DB query '{name}' timed out after {per_query_timeout}s")
        except Exception:
            logger.exception("DB query '%s' failed", name)
            raise

    raw_current_full = results["raw_full"]
    raw_bs = results["raw_bs"]

    if month is not None:
        start = pd.Timestamp(year, month, 1)
        end_y, end_m = month_end_boundary(year, month)
        end = pd.Timestamp(end_y, end_m, 1)
        raw_current_full = raw_current_full[
            (raw_current_full["FECHA"] >= start) & (raw_current_full["FECHA"] < end)
        ].copy()

    return raw_current_full, raw_bs


# ── Single-statement fetch functions (for split dashboard loading) ─────

def fetch_pnl_only(company: str, year: int, conn_factory=None) -> pd.DataFrame:
    """Fetch only P&L data for a single year.  Used by the split dashboard endpoint."""
    if conn_factory is None:
        conn_factory = connect
    t0 = time.perf_counter()
    df = _fetch_with_own_conn(fetch_pnl_data, conn_factory, company, year, None)
    logger.info("fetch_pnl_only %s/%d: %.2fs, %d rows", company, year, time.perf_counter() - t0, len(df))
    return df


def fetch_bs_only(company: str, year: int, conn_factory=None) -> pd.DataFrame:
    """Fetch only BS data for a single year.  Used by the split dashboard endpoint."""
    if conn_factory is None:
        conn_factory = connect
    t0 = time.perf_counter()
    df = _fetch_with_own_conn(fetch_bs_data, conn_factory, company, year, None)
    logger.info("fetch_bs_only %s/%d: %.2fs, %d rows", company, year, time.perf_counter() - t0, len(df))
    return df


# ── Phase C summary fetches (pre-aggregated, ~100–360 rows) ────────────

def fetch_pnl_summary_only(company: str, year: int, conn_factory=None) -> pd.DataFrame:
    """Fetch the pre-aggregated P&L summary for a (company, year).

    Returns ~100 rows; one row per (MES, PARTIDA_PL) with three SALDO columns
    (total / ex_ic / only_ic).  See data.queries.fetch_pnl_summary.
    """
    if conn_factory is None:
        conn_factory = connect
    t0 = time.perf_counter()
    df = _fetch_with_own_conn(fetch_pnl_summary, conn_factory, company, year)
    logger.info("fetch_pnl_summary_only %s/%d: %.2fs, %d rows", company, year, time.perf_counter() - t0, len(df))
    return df


def fetch_bs_summary_only(company: str, year: int, conn_factory=None) -> pd.DataFrame:
    """Fetch the pre-aggregated BS summary for a (company, year).

    Returns ~360 rows; one row per (MES, PARTIDA_BS, SECCION_BS) with the
    sign-corrected cumulative SALDO.  See data.queries.fetch_bs_summary.
    """
    if conn_factory is None:
        conn_factory = connect
    t0 = time.perf_counter()
    df = _fetch_with_own_conn(fetch_bs_summary, conn_factory, company, year)
    logger.info("fetch_bs_summary_only %s/%d: %.2fs, %d rows", company, year, time.perf_counter() - t0, len(df))
    return df


# ── Phase D drill-down fetches (paginated, server-side filter/sort) ────

def fetch_pnl_detail_only(company: str, year_month_pairs, partida: str, *,
                          offset: int = 0, limit: int = 500,
                          filter_col=None, filter_val=None,
                          ic_filter: str = "all",
                          conn_factory=None) -> pd.DataFrame:
    """One-page P&L journal-entry drill-down. See data.queries.fetch_pnl_detail."""
    if conn_factory is None:
        conn_factory = connect
    t0 = time.perf_counter()
    df = _fetch_with_own_conn(
        fetch_pnl_detail, conn_factory, company, year_month_pairs, partida,
        offset=offset, limit=limit,
        filter_col=filter_col, filter_val=filter_val, ic_filter=ic_filter,
    )
    logger.info("fetch_pnl_detail_only %s/%s offset=%d limit=%d: %.2fs, %d rows",
                company, partida, offset, limit, time.perf_counter() - t0, len(df))
    return df


def fetch_pnl_detail_count_only(company: str, year_month_pairs, partida: str, *,
                                filter_col=None, filter_val=None,
                                ic_filter: str = "all",
                                conn_factory=None) -> int:
    """COUNT(*) for the P&L detail query — same WHERE clause."""
    if conn_factory is None:
        conn_factory = connect
    t0 = time.perf_counter()
    n = _fetch_with_own_conn(
        fetch_pnl_detail_count, conn_factory, company, year_month_pairs, partida,
        filter_col=filter_col, filter_val=filter_val, ic_filter=ic_filter,
    )
    logger.info("fetch_pnl_detail_count_only %s/%s: %.2fs, %d",
                company, partida, time.perf_counter() - t0, n)
    return n


def fetch_bs_detail_only(company: str, year_month_pairs, partida: str, *,
                         offset: int = 0, limit: int = 500,
                         filter_col=None, filter_val=None,
                         ic_filter: str = "all",
                         conn_factory=None) -> pd.DataFrame:
    """One-page BS journal-entry drill-down. See data.queries.fetch_bs_detail."""
    if conn_factory is None:
        conn_factory = connect
    t0 = time.perf_counter()
    df = _fetch_with_own_conn(
        fetch_bs_detail, conn_factory, company, year_month_pairs, partida,
        offset=offset, limit=limit,
        filter_col=filter_col, filter_val=filter_val, ic_filter=ic_filter,
    )
    logger.info("fetch_bs_detail_only %s/%s offset=%d limit=%d: %.2fs, %d rows",
                company, partida, offset, limit, time.perf_counter() - t0, len(df))
    return df


def fetch_bs_detail_count_only(company: str, year_month_pairs, partida: str, *,
                               filter_col=None, filter_val=None,
                               ic_filter: str = "all",
                               conn_factory=None) -> int:
    """COUNT(*) for the BS detail query — same WHERE clause."""
    if conn_factory is None:
        conn_factory = connect
    t0 = time.perf_counter()
    n = _fetch_with_own_conn(
        fetch_bs_detail_count, conn_factory, company, year_month_pairs, partida,
        filter_col=filter_col, filter_val=filter_val, ic_filter=ic_filter,
    )
    logger.info("fetch_bs_detail_count_only %s/%s: %.2fs, %d",
                company, partida, time.perf_counter() - t0, n)
    return n
