"""Data fetching — per-query DB calls for the dashboard, each on its own connection."""

import logging
import time

import pandas as pd

from data.db import connect
from data.queries import (
    fetch_pnl_summary, fetch_bs_summary,
    fetch_pnl_preagg, fetch_bs_detalle_cuenta, fetch_bs_detalle_nit,
    fetch_bs_last_month,
    fetch_pnl_detail, fetch_pnl_detail_count,
    fetch_bs_detail, fetch_bs_detail_count,
)


logger = logging.getLogger("plantillas.data_fetcher")


def _fetch_with_own_conn(fetch_fn, conn_factory, *args, **kwargs) -> pd.DataFrame:
    """Run *fetch_fn* using its own database connection (thread-safe)."""
    with conn_factory() as conn:
        return fetch_fn(conn, *args, **kwargs)


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


# ── Phase F detail-grain fetches (pre-aggregated section + note tables) ─

def fetch_pnl_preagg_only(company: str, year: int, conn_factory=None) -> pd.DataFrame:
    """Fetch the pre-aggregated P&L detail grain for a (company, year).

    One row per (MES, PARTIDA_PL, CECO, CUENTA, NIT) with three SALDO columns.
    Feeds every P&L section table + ex_ic/only_ic variants.
    See data.queries.fetch_pnl_preagg.
    """
    if conn_factory is None:
        conn_factory = connect
    t0 = time.perf_counter()
    df = _fetch_with_own_conn(fetch_pnl_preagg, conn_factory, company, year)
    logger.info("fetch_pnl_preagg_only %s/%d: %.2fs, %d rows", company, year, time.perf_counter() - t0, len(df))
    return df


def fetch_bs_detalle_cuenta_only(company: str, year: int, partidas: list[str],
                                 conn_factory=None) -> pd.DataFrame:
    """Fetch cuenta-grain cumulative BS balances for the given PARTIDA_BS list.

    Backs bs_detail_by_cuenta. See data.queries.fetch_bs_detalle_cuenta.
    """
    if conn_factory is None:
        conn_factory = connect
    t0 = time.perf_counter()
    df = _fetch_with_own_conn(fetch_bs_detalle_cuenta, conn_factory, company, year, partidas)
    logger.info("fetch_bs_detalle_cuenta_only %s/%d: %.2fs, %d rows", company, year, time.perf_counter() - t0, len(df))
    return df


def fetch_bs_last_month_only(company: str, year: int, conn_factory=None) -> int | None:
    """Return the last month (1–12) with posted BS activity, or None.

    See data.queries.fetch_bs_last_month.  Cheap single-aggregate roundtrip.
    """
    if conn_factory is None:
        conn_factory = connect
    return _fetch_with_own_conn(fetch_bs_last_month, conn_factory, company, year)


def fetch_bs_detalle_nit_only(company: str, year: int, partidas: list[str],
                              conn_factory=None) -> pd.DataFrame:
    """Fetch NIT-grain cumulative BS balances for the given PARTIDA_BS list.

    Backs bs_top20_by_nit. See data.queries.fetch_bs_detalle_nit.
    """
    if conn_factory is None:
        conn_factory = connect
    t0 = time.perf_counter()
    df = _fetch_with_own_conn(fetch_bs_detalle_nit, conn_factory, company, year, partidas)
    logger.info("fetch_bs_detalle_nit_only %s/%d: %.2fs, %d rows", company, year, time.perf_counter() - t0, len(df))
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
