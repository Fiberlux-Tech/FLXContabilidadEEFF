import logging
from datetime import date

import pandas as pd
import pyodbc

from config.period import month_end_boundary
from config.exceptions import QueryError
from config.fields import PARTIDA_PL, PARTIDA_BS


logger = logging.getLogger("plantillas.queries")

SQL_SCHEMA = "REPORTES"
SQL_VIEW = "VISTA_ANALISIS_CECOS"
SQL_VIEW_PNL_PREPARADO = "VISTA_PNL_PREPARADO"
SQL_VIEW_BS_PREPARADO = "VISTA_BS_PREPARADO"
SQL_VIEW_PNL_SUMARIO = "VISTA_PNL_SUMARIO"
SQL_VIEW_BS_SUMARIO = "VISTA_BS_SUMARIO"
SQL_VIEW_PNL_PREAGG = "VISTA_PNL_PREAGG"
SQL_VIEW_BS_PREPARADO_CUMSUM = "VISTA_BS_PREPARADO_CUMSUM"
SQL_VIEW_BS_DETALLE_NIT_CUMSUM = "VISTA_BS_DETALLE_NIT_CUMSUM"

# Validate identifiers at import time to prevent any injection via constants.
import re as _re
_IDENT_RE = _re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
for _ident in (SQL_SCHEMA, SQL_VIEW, SQL_VIEW_PNL_PREPARADO, SQL_VIEW_BS_PREPARADO,
               SQL_VIEW_PNL_SUMARIO, SQL_VIEW_BS_SUMARIO, SQL_VIEW_PNL_PREAGG,
               SQL_VIEW_BS_PREPARADO_CUMSUM, SQL_VIEW_BS_DETALLE_NIT_CUMSUM):
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


# ── Phase F: pre-aggregated detail-grain fetches (section + note tables) ──
#
# These replace the in-Python preaggregate(df_stmt) / df_bs groupby that the
# P&L section tables and BS note tables used to run on a cached row-level
# DataFrame. The views do the GROUP BY; Python keeps only the cheap shaping
# (pivot MES→columns, sort, TOTAL row, prefix split, top-N rank).


def fetch_pnl_preagg(conn: pyodbc.Connection, company: str, year: int) -> pd.DataFrame:
    """Fetch the pre-aggregated P&L detail grain from REPORTES.VISTA_PNL_PREAGG.

    The view groups VISTA_PNL_PREPARADO (statement-eligible rows) by
    (CIA, YEAR, MES, PARTIDA_PL, CENTRO_COSTO, DESC_CECO, CUENTA_CONTABLE,
    DESCRIPCION, NIT, RAZON_SOCIAL) and returns three SALDO columns per row
    (SALDO_TOTAL / SALDO_EX_IC / SALDO_ONLY_IC). One fetch feeds every P&L
    section table and its ex_ic / only_ic variants — the caller derives the
    three preagg frames by picking the matching SALDO_* column.

    Returns ~10²–10³ rows per (company, year), not the 8.4M raw rows.
    """
    query = (
        "SELECT MES, PARTIDA_PL, CENTRO_COSTO, DESC_CECO, "
        "CUENTA_CONTABLE, DESCRIPCION, NIT, RAZON_SOCIAL, "
        "SALDO_TOTAL, SALDO_EX_IC, SALDO_ONLY_IC "
        f"FROM {SQL_SCHEMA}.{SQL_VIEW_PNL_PREAGG} "
        "WHERE CIA = ? AND YEAR = ?"
    )
    params = [company, year]
    logger.debug("PNL preagg query: %s | params: %s", query, params)
    try:
        result = pd.read_sql(query, conn, params=params)
    except (pyodbc.Error, pd.errors.DatabaseError) as exc:
        raise QueryError(f"Failed to fetch P&L preagg for {company}/{year}: {exc}") from exc

    logger.info("Fetched %d P&L preagg rows for %s/%s", len(result), company, year)
    return result


def fetch_bs_detalle_cuenta(conn: pyodbc.Connection, company: str, year: int,
                            partidas: list[str]) -> pd.DataFrame:
    """Fetch cuenta-grain cumulative BS balances from VISTA_BS_PREPARADO_CUMSUM.

    Backs bs_detail_by_cuenta. The CUMSUM view (Phase E) is already at exactly
    the cuenta grain this note builder needs, so no Phase F view is required —
    we query it directly with a PARTIDA_BS IN (...) filter. The cuenta-prefix
    include/exclude, future-month handling, and TOTAL stay in Python.

    *partidas* must be non-empty; the IN-list is parameterized.
    """
    if not partidas:
        raise QueryError("partidas must be non-empty")
    placeholders = ", ".join(["?"] * len(partidas))
    query = (
        "SELECT MES, CUENTA_CONTABLE, DESCRIPCION, SALDO_CUMSUM "
        f"FROM {SQL_SCHEMA}.{SQL_VIEW_BS_PREPARADO_CUMSUM} "
        f"WHERE CIA = ? AND YEAR = ? AND PARTIDA_BS IN ({placeholders})"
    )
    params = [company, year, *partidas]
    logger.debug("BS detalle cuenta query: %s | params: %s", query, params)
    try:
        result = pd.read_sql(query, conn, params=params)
    except (pyodbc.Error, pd.errors.DatabaseError) as exc:
        raise QueryError(f"Failed to fetch BS cuenta detalle for {company}/{year}: {exc}") from exc

    logger.info("Fetched %d BS cuenta detalle rows for %s/%s", len(result), company, year)
    return result


def fetch_bs_last_month(conn: pyodbc.Connection, company: str, year: int) -> int | None:
    """Return the last month (1–12) with posted BS activity, or None if no rows.

    Reads MAX(MES) from the row-level VISTA_BS_PREPARADO — rows exist iff there
    was a journal entry that month, so this is "last month with data", not the
    calendar month.  The cumsum views are densified to all 12 months and so
    cannot supply this; the BS note builders need it to zero out future months
    and to set TOTAL = the last-activity-month balance (parity with the
    pre-Phase-F path, which read df[MES].max() on the raw frame).
    """
    query = (
        "SELECT MAX(MES) "
        f"FROM {SQL_SCHEMA}.{SQL_VIEW_BS_PREPARADO} "
        "WHERE CIA = ? AND YEAR = ?"
    )
    params = [company, year]
    logger.debug("BS last-month query: %s | params: %s", query, params)
    try:
        cur = conn.cursor()
        cur.execute(query, params)
        row = cur.fetchone()
    except (pyodbc.Error, pd.errors.DatabaseError) as exc:
        raise QueryError(f"Failed to fetch BS last month for {company}/{year}: {exc}") from exc
    if row is None or row[0] is None:
        return None
    return int(row[0])


def fetch_bs_detalle_nit(conn: pyodbc.Connection, company: str, year: int,
                         partidas: list[str]) -> pd.DataFrame:
    """Fetch NIT-grain cumulative BS balances from VISTA_BS_DETALLE_NIT_CUMSUM.

    Backs bs_top20_by_nit. The view applies the densified cumsum per
    (partida, NIT); Python pivots, zeroes future months, ranks top-20,
    fills SIN NIT / SIN RAZON SOCIAL, and appends the TOTAL row.

    *partidas* must be non-empty; the IN-list is parameterized.
    """
    if not partidas:
        raise QueryError("partidas must be non-empty")
    placeholders = ", ".join(["?"] * len(partidas))
    query = (
        "SELECT MES, NIT, RAZON_SOCIAL, SALDO_CUMSUM "
        f"FROM {SQL_SCHEMA}.{SQL_VIEW_BS_DETALLE_NIT_CUMSUM} "
        f"WHERE CIA = ? AND YEAR = ? AND PARTIDA_BS IN ({placeholders})"
    )
    params = [company, year, *partidas]
    logger.debug("BS detalle NIT query: %s | params: %s", query, params)
    try:
        result = pd.read_sql(query, conn, params=params)
    except (pyodbc.Error, pd.errors.DatabaseError) as exc:
        raise QueryError(f"Failed to fetch BS NIT detalle for {company}/{year}: {exc}") from exc

    logger.info("Fetched %d BS NIT detalle rows for %s/%s", len(result), company, year)
    return result


# ── Phase D: drill-down detail (paginated, server-side filter/sort) ──────
#
# These functions back the /api/data/detail endpoint. The row-level
# VISTA_*_PREPARADO views are the source; pagination uses OFFSET ... FETCH.
# Column-name whitelisting is defense-in-depth at the SQL boundary — the
# routes layer also validates, but queries.py enforces independently.

_DETAIL_SELECT_COLS = (
    "ASIENTO, CUENTA_CONTABLE, DESCRIPCION, NIT, RAZON_SOCIAL, "
    "CENTRO_COSTO, DESC_CECO, FECHA, SALDO"
)

# Columns whose values may be substring-matched via WHERE <col> LIKE ?
_DETAIL_FILTER_COLS: frozenset[str] = frozenset({
    "ASIENTO", "CUENTA_CONTABLE", "DESCRIPCION",
    "NIT", "RAZON_SOCIAL", "CENTRO_COSTO", "DESC_CECO",
})

_IC_FILTER_CLAUSES = {
    "all": "",
    "ex_ic": " AND IS_INTERCOMPANY = 0",
    "only_ic": " AND IS_INTERCOMPANY = 1",
}

# Wildcard chars that must be neutralised before wrapping the user-supplied
# filter value with %...% for a partial-match LIKE.
_LIKE_WILDCARDS = ("\\", "%", "_", "[")


def _escape_like(val: str) -> str:
    """Escape LIKE wildcards so user input matches literally inside %...%."""
    for ch in _LIKE_WILDCARDS:
        val = val.replace(ch, "\\" + ch)
    return val


def _build_detail_where(view_name: str, partida_col: str,
                        year_month_pairs: list[tuple[int, int]],
                        *, eligible_clause: str,
                        filter_col: str | None, ic_filter: str) -> tuple[str, list]:
    """Build the shared WHERE clause + params for fetch_*_detail and counts.

    Returns (where_sql, params). Caller appends ORDER BY / OFFSET / FETCH or
    SELECT COUNT(*) wrapping.

    Validates *partida_col*, *filter_col*, *ic_filter* against constants; the
    only thing interpolated into SQL is whitelisted column / view names.
    """
    if partida_col not in (PARTIDA_PL, PARTIDA_BS):
        raise QueryError(f"Invalid partida column: {partida_col!r}")
    if ic_filter not in _IC_FILTER_CLAUSES:
        raise QueryError(f"Invalid ic_filter: {ic_filter!r}")
    if not year_month_pairs:
        raise QueryError("year_month_pairs must be non-empty")
    if filter_col is not None and filter_col not in _DETAIL_FILTER_COLS:
        raise QueryError(f"Invalid filter_col: {filter_col!r}")

    # SQL Server doesn't accept (YEAR, MES) IN ((?,?), ...) row-constructor
    # syntax — error 4145 ("non-boolean type ... near ','").  Use an OR-chain
    # of equality pairs instead; the optimizer plans them identically.
    pair_clause = " OR ".join(["(YEAR = ? AND MES = ?)"] * len(year_month_pairs))
    where = (
        f"FROM {SQL_SCHEMA}.{view_name} "
        f"WHERE CIA = ? AND {partida_col} = ?"
        f"{eligible_clause}"
        f" AND ({pair_clause})"
        f"{_IC_FILTER_CLAUSES[ic_filter]}"
    )
    params: list = []  # CIA + partida are added by caller (it knows them)
    for year, mes in year_month_pairs:
        params.extend([year, mes])
    if filter_col is not None:
        where += f" AND {filter_col} LIKE ? ESCAPE '\\'"
    return where, params


def _run_detail_query(conn: pyodbc.Connection, view_name: str, partida_col: str,
                      company: str, partida: str,
                      year_month_pairs: list[tuple[int, int]],
                      *, eligible_clause: str,
                      offset: int, limit: int,
                      filter_col: str | None, filter_val: str | None,
                      ic_filter: str) -> pd.DataFrame:
    if offset < 0 or limit < 1:
        raise QueryError(f"Invalid pagination: offset={offset}, limit={limit}")
    where, where_params = _build_detail_where(
        view_name, partida_col, year_month_pairs,
        eligible_clause=eligible_clause, filter_col=filter_col, ic_filter=ic_filter,
    )
    query = (
        f"SELECT {_DETAIL_SELECT_COLS} {where} "
        "ORDER BY SALDO DESC, ASIENTO, CUENTA_CONTABLE "
        "OFFSET ? ROWS FETCH NEXT ? ROWS ONLY"
    )
    params: list = [company, partida, *where_params]
    if filter_col is not None and filter_val is not None:
        params.append(f"%{_escape_like(filter_val)}%")
    params.extend([offset, limit])
    logger.debug("Detail query: %s | params: %s", query, params)
    try:
        result = pd.read_sql(query, conn, params=params)
    except (pyodbc.Error, pd.errors.DatabaseError) as exc:
        raise QueryError(
            f"Failed to fetch detail for {company}/{partida} ({view_name}): {exc}"
        ) from exc
    return result


def _run_detail_count(conn: pyodbc.Connection, view_name: str, partida_col: str,
                      company: str, partida: str,
                      year_month_pairs: list[tuple[int, int]],
                      *, eligible_clause: str,
                      filter_col: str | None, filter_val: str | None,
                      ic_filter: str) -> int:
    where, where_params = _build_detail_where(
        view_name, partida_col, year_month_pairs,
        eligible_clause=eligible_clause, filter_col=filter_col, ic_filter=ic_filter,
    )
    query = f"SELECT COUNT(*) {where}"
    params: list = [company, partida, *where_params]
    if filter_col is not None and filter_val is not None:
        params.append(f"%{_escape_like(filter_val)}%")
    try:
        cur = conn.cursor()
        cur.execute(query, params)
        row = cur.fetchone()
    except (pyodbc.Error, pd.errors.DatabaseError) as exc:
        raise QueryError(
            f"Failed to count detail for {company}/{partida} ({view_name}): {exc}"
        ) from exc
    return int(row[0])


def fetch_pnl_detail(conn: pyodbc.Connection, company: str,
                     year_month_pairs: list[tuple[int, int]], partida: str,
                     *, offset: int = 0, limit: int = 500,
                     filter_col: str | None = None, filter_val: str | None = None,
                     ic_filter: str = "all") -> pd.DataFrame:
    """Paginated journal-entry drill-down from VISTA_PNL_PREPARADO.

    Filters to statement-eligible rows only.  *year_month_pairs* lets one
    query span multiple months in (potentially) multiple years — used for
    multi-month cell selections and trailing-12M views.

    Returns a DataFrame of up to *limit* rows ordered by
    SALDO DESC, ASIENTO, CUENTA_CONTABLE (stable for pagination).
    """
    df = _run_detail_query(
        conn, SQL_VIEW_PNL_PREPARADO, PARTIDA_PL, company, partida, year_month_pairs,
        eligible_clause=" AND IS_STATEMENT_ELIGIBLE = 1",
        offset=offset, limit=limit,
        filter_col=filter_col, filter_val=filter_val, ic_filter=ic_filter,
    )
    logger.info("Fetched %d P&L detail rows for %s/%s (offset=%d, limit=%d)",
                len(df), company, partida, offset, limit)
    return df


def fetch_pnl_detail_count(conn: pyodbc.Connection, company: str,
                           year_month_pairs: list[tuple[int, int]], partida: str,
                           *, filter_col: str | None = None, filter_val: str | None = None,
                           ic_filter: str = "all") -> int:
    """COUNT(*) companion for fetch_pnl_detail — same WHERE clause."""
    n = _run_detail_count(
        conn, SQL_VIEW_PNL_PREPARADO, PARTIDA_PL, company, partida, year_month_pairs,
        eligible_clause=" AND IS_STATEMENT_ELIGIBLE = 1",
        filter_col=filter_col, filter_val=filter_val, ic_filter=ic_filter,
    )
    logger.info("Counted %d P&L detail rows for %s/%s", n, company, partida)
    return n


def fetch_bs_detail(conn: pyodbc.Connection, company: str,
                    year_month_pairs: list[tuple[int, int]], partida: str,
                    *, offset: int = 0, limit: int = 500,
                    filter_col: str | None = None, filter_val: str | None = None,
                    ic_filter: str = "all") -> pd.DataFrame:
    """Paginated journal-entry drill-down from VISTA_BS_PREPARADO.

    No eligibility flag on BS — every class 1-5 row is eligible.  Same
    pagination + ordering contract as fetch_pnl_detail.
    """
    df = _run_detail_query(
        conn, SQL_VIEW_BS_PREPARADO, PARTIDA_BS, company, partida, year_month_pairs,
        eligible_clause="",
        offset=offset, limit=limit,
        filter_col=filter_col, filter_val=filter_val, ic_filter=ic_filter,
    )
    logger.info("Fetched %d BS detail rows for %s/%s (offset=%d, limit=%d)",
                len(df), company, partida, offset, limit)
    return df


def fetch_bs_detail_count(conn: pyodbc.Connection, company: str,
                          year_month_pairs: list[tuple[int, int]], partida: str,
                          *, filter_col: str | None = None, filter_val: str | None = None,
                          ic_filter: str = "all") -> int:
    """COUNT(*) companion for fetch_bs_detail — same WHERE clause."""
    n = _run_detail_count(
        conn, SQL_VIEW_BS_PREPARADO, PARTIDA_BS, company, partida, year_month_pairs,
        eligible_clause="",
        filter_col=filter_col, filter_val=filter_val, ic_filter=ic_filter,
    )
    logger.info("Counted %d BS detail rows for %s/%s", n, company, partida)
    return n
