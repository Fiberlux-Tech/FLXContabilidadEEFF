import logging
from datetime import date

import pandas as pd
import pyodbc

from accounting.rules import BS_ACCOUNT_PREFIXES
from config.period import month_end_boundary
from config.exceptions import QueryError


logger = logging.getLogger("plantillas.queries")

SQL_SCHEMA = "REPORTES"
SQL_VIEW = "VISTA_ANALISIS_CECOS"
SQL_VIEW_PNL_PREPARADO = "VISTA_PNL_PREPARADO"

# Validate identifiers at import time to prevent any injection via constants.
import re as _re
_IDENT_RE = _re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
for _ident in (SQL_SCHEMA, SQL_VIEW, SQL_VIEW_PNL_PREPARADO):
    if not _IDENT_RE.match(_ident):
        raise ValueError(f"Invalid SQL identifier: {_ident!r}")


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

    end_y, end_m = month_end_boundary(year, month)
    end = date(end_y, end_m, 1)

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
        "CENTRO_COSTO, DESC_CECO, FECHA, DEBITO_LOCAL, CREDITO_LOCAL, ASIENTO "
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


def fetch_pnl_data(conn: pyodbc.Connection, company: str, year: int, month: int | None = None,
                   *, eligible_only: bool = True) -> pd.DataFrame:
    """Fetch P&L data from REPORTES.VISTA_PNL_PREPARADO.

    The view enriches each row with SALDO, MES, PARTIDA_PL, IS_INTERCOMPANY,
    and IS_STATEMENT_ELIGIBLE. It already applies the classes 6/7/8 prefix
    filter and excludes FUENTE LIKE 'CIERRE%', so callers no longer need
    to repeat those.

    Parameters
    ----------
    eligible_only : bool, default True
        When True (the statement path used by the dashboard and PDF), the
        query filters to rows where IS_STATEMENT_ELIGIBLE = 1 (the view's
        encoding of "first-3-digits >= 619 and CUENTA <> '79.1.1.1.01'").
        When False (the Excel raw-pivot path), all P&L rows are returned,
        including inventory-side accounts like 60.x that feed the raw
        by_cuenta / by_ceco / by_ceco_cuenta sheets.
    """
    if month is None:
        start = date(year, 1, 1)
    else:
        start = date(year, month, 1)
    end_y, end_m = month_end_boundary(year, month)
    end = date(end_y, end_m, 1)

    # When eligible_only=True we filter in SQL; the column itself is
    # uninteresting downstream so we omit it. When False (Excel raw path),
    # we return all rows and surface the column so callers can subset.
    eligibility_clause = " AND IS_STATEMENT_ELIGIBLE = 1" if eligible_only else ""
    extra_select = "" if eligible_only else ", IS_STATEMENT_ELIGIBLE"

    query = (
        "SELECT CIA, CUENTA_CONTABLE, DESCRIPCION, NIT, RAZON_SOCIAL, "
        "CENTRO_COSTO, DESC_CECO, FECHA, DEBITO_LOCAL, CREDITO_LOCAL, ASIENTO, "
        f"SALDO, MES, PARTIDA_PL, IS_INTERCOMPANY{extra_select} "
        f"FROM {SQL_SCHEMA}.{SQL_VIEW_PNL_PREPARADO} "
        f"WHERE CIA = ? AND FECHA >= ? AND FECHA < ?{eligibility_clause}"
    )

    params = [company, start, end]
    logger.debug("PNL view query: %s | params: %s", query, params)
    try:
        result = pd.read_sql(query, conn, params=params)
    except (pyodbc.Error, pd.errors.DatabaseError) as exc:
        raise QueryError(f"Failed to fetch P&L for {company}/{year}: {exc}") from exc

    logger.info("Fetched %d P&L rows for %s/%s (eligible_only=%s)",
                len(result), company, year, eligible_only)
    return result


def fetch_bs_data(conn: pyodbc.Connection, company: str, year: int, month: int | None = None) -> pd.DataFrame:
    """Fetch BS accounts (classes 1-5) cumulatively from Jan 1 through period end.

    Year-end closing entries (FUENTE LIKE 'CIERRE%') are excluded so that
    cumulative balances reflect actual account balances rather than being
    zeroed out by the closing journal entry.
    """
    return _fetch_data(conn, company, year, month, BS_ACCOUNT_PREFIXES, cumulative=True, exclude_closing=True)
