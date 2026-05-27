import logging
from datetime import date

import pandas as pd
import pyodbc

from config.period import month_end_boundary
from config.exceptions import QueryError


logger = logging.getLogger("plantillas.queries")

SQL_SCHEMA = "REPORTES"
SQL_VIEW = "VISTA_ANALISIS_CECOS"
SQL_VIEW_PNL_PREPARADO = "VISTA_PNL_PREPARADO"
SQL_VIEW_BS_PREPARADO = "VISTA_BS_PREPARADO"
SQL_VIEW_PNL_SUMARIO = "VISTA_PNL_SUMARIO"
SQL_VIEW_BS_SUMARIO = "VISTA_BS_SUMARIO"

# Validate identifiers at import time to prevent any injection via constants.
import re as _re
_IDENT_RE = _re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
for _ident in (SQL_SCHEMA, SQL_VIEW, SQL_VIEW_PNL_PREPARADO, SQL_VIEW_BS_PREPARADO,
               SQL_VIEW_PNL_SUMARIO, SQL_VIEW_BS_SUMARIO):
    if not _IDENT_RE.match(_ident):
        raise ValueError(f"Invalid SQL identifier: {_ident!r}")


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
    """Fetch BS data from REPORTES.VISTA_BS_PREPARADO.

    The view enriches each row with SALDO, MES, PARTIDA_BS, SECCION_BS. It
    already restricts to classes 1-5 and excludes FUENTE LIKE 'CIERRE%', so
    callers no longer need to repeat those filters. Always cumulative from
    Jan 1 — BS reports balances as of period end.

    Unlike fetch_pnl_data, there is no eligible_only flag — BS has no
    statement-eligibility distinction; every class 1-5 row feeds both the
    statement and the raw pivot tables.
    """
    start = date(year, 1, 1)
    end_y, end_m = month_end_boundary(year, month)
    end = date(end_y, end_m, 1)

    query = (
        "SELECT CIA, CUENTA_CONTABLE, DESCRIPCION, NIT, RAZON_SOCIAL, "
        "CENTRO_COSTO, DESC_CECO, FECHA, DEBITO_LOCAL, CREDITO_LOCAL, ASIENTO, "
        "SALDO, MES, PARTIDA_BS, SECCION_BS "
        f"FROM {SQL_SCHEMA}.{SQL_VIEW_BS_PREPARADO} "
        "WHERE CIA = ? AND FECHA >= ? AND FECHA < ?"
    )
    params = [company, start, end]
    logger.debug("BS view query: %s | params: %s", query, params)
    try:
        result = pd.read_sql(query, conn, params=params)
    except (pyodbc.Error, pd.errors.DatabaseError) as exc:
        raise QueryError(f"Failed to fetch BS for {company}/{year}: {exc}") from exc

    logger.info("Fetched %d BS rows for %s/%s", len(result), company, year)
    return result


def fetch_pnl_summary(conn: pyodbc.Connection, company: str, year: int) -> pd.DataFrame:
    """Fetch the pre-aggregated P&L summary from REPORTES.VISTA_PNL_SUMARIO.

    The view groups VISTA_PNL_PREPARADO by (CIA, YEAR, MES, PARTIDA_PL) and
    returns three SALDO columns in one row: SALDO_TOTAL, SALDO_EX_IC (non-
    intercompany only), and SALDO_ONLY_IC (intercompany only). The dashboard
    builds all three pl_summary variants from one SQL roundtrip.

    Returns ~100 rows per (company, year).
    """
    query = (
        "SELECT MES, PARTIDA_PL, SALDO_TOTAL, SALDO_EX_IC, SALDO_ONLY_IC "
        f"FROM {SQL_SCHEMA}.{SQL_VIEW_PNL_SUMARIO} "
        "WHERE CIA = ? AND YEAR = ?"
    )
    params = [company, year]
    logger.debug("PNL summary query: %s | params: %s", query, params)
    try:
        result = pd.read_sql(query, conn, params=params)
    except (pyodbc.Error, pd.errors.DatabaseError) as exc:
        raise QueryError(f"Failed to fetch P&L summary for {company}/{year}: {exc}") from exc

    logger.info("Fetched %d P&L summary rows for %s/%s", len(result), company, year)
    return result


def fetch_bs_summary(conn: pyodbc.Connection, company: str, year: int) -> pd.DataFrame:
    """Fetch the pre-aggregated BS summary from REPORTES.VISTA_BS_SUMARIO.

    The view sits on VISTA_BS_PREPARADO_CUMSUM, applies the three
    reclassification rules + native-section sign flips in SQL, and groups
    to partida-grain per month. SALDO is each month's cumulative balance
    (sign-corrected).

    Returns ~30 partidas × 12 months = ~360 rows per (company, year).
    """
    query = (
        "SELECT MES, PARTIDA_BS, SECCION_BS, SALDO "
        f"FROM {SQL_SCHEMA}.{SQL_VIEW_BS_SUMARIO} "
        "WHERE CIA = ? AND YEAR = ?"
    )
    params = [company, year]
    logger.debug("BS summary query: %s | params: %s", query, params)
    try:
        result = pd.read_sql(query, conn, params=params)
    except (pyodbc.Error, pd.errors.DatabaseError) as exc:
        raise QueryError(f"Failed to fetch BS summary for {company}/{year}: {exc}") from exc

    logger.info("Fetched %d BS summary rows for %s/%s", len(result), company, year)
    return result
