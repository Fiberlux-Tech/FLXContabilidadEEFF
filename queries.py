import logging
from datetime import date

import pandas as pd
import pyodbc

from account_rules import BS_ACCOUNT_PREFIXES
from exceptions import QueryError


logger = logging.getLogger("plantillas.queries")

SQL_SCHEMA = "REPORTES"
SQL_VIEW = "VISTA_ANALISIS_CECOS"

# Validate identifiers at import time to prevent any injection via constants.
import re as _re
_IDENT_RE = _re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
if not _IDENT_RE.match(SQL_SCHEMA) or not _IDENT_RE.match(SQL_VIEW):
    raise ValueError(f"Invalid SQL identifier: {SQL_SCHEMA!r} / {SQL_VIEW!r}")

PNL_ACCOUNT_PREFIXES = ("6", "7", "8")


def _fetch_data(conn: pyodbc.Connection, company: str, year: int, month: int | None, account_prefixes: tuple[str, ...], *, cumulative: bool = False, exclude_closing: bool = False) -> pd.DataFrame:
    """Shared helper for fetching accounting data from the SQL view.

    Parameters
    ----------
    conn : database connection
    company : str
    year : int
    month : int or None
    account_prefixes : tuple[str, ...]
        Leading characters to filter CUENTA_CONTABLE (e.g. ("6","7","8")).
    cumulative : bool
        If True the start date is always Jan 1 (Balance Sheet behaviour).
        If False the start date matches the requested month (P&L behaviour).
    exclude_closing : bool
        If True, exclude year-end closing entries (FUENTE LIKE 'CIERRE%').
    """
    # --- date range ---
    if cumulative:
        start = date(year, 1, 1)
    else:
        start = date(year, month, 1) if month is not None else date(year, 1, 1)

    if month is not None:
        end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    else:
        end = date(year + 1, 1, 1)

    # Build account-prefix filter using LIKE for index seekability (SARGable)
    if account_prefixes:
        like_clauses = " OR ".join("CUENTA_CONTABLE LIKE ?" for _ in account_prefixes)
        acct_clause = f" AND ({like_clauses})"
    else:
        acct_clause = ""

    closing_clause = " AND FUENTE NOT LIKE 'CIERRE%'" if exclude_closing else ""

    # LTRIM/RTRIM removed — whitespace trimming should be handled in the ETL
    # or directly in the SQL view (VISTA_ANALISIS_CECOS) to avoid per-query overhead.
    query = (
        "SELECT CIA, CUENTA_CONTABLE, DESCRIPCION, NIT, RAZON_SOCIAL, "
        "CENTRO_COSTO, DESC_CECO, FECHA, DEBITO_LOCAL, CREDITO_LOCAL "
        f"FROM {SQL_SCHEMA}.{SQL_VIEW} "
        f"WHERE CIA = ? AND FECHA >= ? AND FECHA < ?{acct_clause}{closing_clause}"
    )

    params = ([company, start, end] + [f"{p}%" for p in account_prefixes]) if account_prefixes else [company, start, end]
    logger.debug("SQL query: %s | params: %s", query, params)
    try:
        result = pd.read_sql(query, conn, params=params)
    except (pyodbc.Error, pd.errors.DatabaseError) as exc:
        raise QueryError(f"Failed to fetch data for {company}/{year}: {exc}") from exc

    logger.info("Fetched %d rows for %s/%s", len(result), company, year)
    return result


def fetch_pnl_data(conn: pyodbc.Connection, company: str, year: int, month: int | None = None) -> pd.DataFrame:
    """Fetch P&L accounts (classes 6-8) for the requested period.

    Year-end closing entries (FUENTE LIKE 'CIERRE%') are excluded so that
    account balances are not zeroed out by the closing journal entry.
    """
    return _fetch_data(conn, company, year, month, PNL_ACCOUNT_PREFIXES, cumulative=False, exclude_closing=True)


def fetch_bs_data(conn: pyodbc.Connection, company: str, year: int, month: int | None = None) -> pd.DataFrame:
    """Fetch BS accounts (classes 1-5) cumulatively from Jan 1 through period end.

    Year-end closing entries (FUENTE LIKE 'CIERRE%') are excluded so that
    cumulative balances reflect actual account balances rather than being
    zeroed out by the closing journal entry.
    """
    return _fetch_data(conn, company, year, month, BS_ACCOUNT_PREFIXES, cumulative=True, exclude_closing=True)
