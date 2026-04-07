"""SQLite-backed storage for employee roster data.

Headcount is computed on-the-fly via COUNT(DISTINCT empleado) — no
pre-aggregated table needed.
"""

import logging
import os
import sqlite3

logger = logging.getLogger("flxcontabilidad.headcount_db")

_DEFAULT_DB = os.path.join(os.path.dirname(__file__), "headcount.db")

_CREATE_ROSTER = """\
CREATE TABLE IF NOT EXISTS employee_roster (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    cia          TEXT    NOT NULL,
    centro_costo TEXT    NOT NULL,
    year_month   INTEGER NOT NULL,
    empleado     TEXT    NOT NULL,
    nombre       TEXT    NOT NULL DEFAULT '',
    UNIQUE(cia, centro_costo, year_month, empleado)
);
"""

_CREATE_INDEX = """\
CREATE INDEX IF NOT EXISTS idx_roster_cia_ym
    ON employee_roster(cia, year_month);
"""

_CREATE_INDEX_DETAIL = """\
CREATE INDEX IF NOT EXISTS idx_roster_cia_ceco_ym
    ON employee_roster(cia, centro_costo, year_month);
"""


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_headcount_db(db_path: str | None = None) -> str:
    """Create the roster table + indexes if they don't exist.

    Returns the resolved db_path so callers can store it.
    """
    db_path = db_path or _DEFAULT_DB
    with _connect(db_path) as conn:
        conn.execute(_CREATE_ROSTER)
        conn.execute(_CREATE_INDEX)
        conn.execute(_CREATE_INDEX_DETAIL)
    logger.info("Headcount DB initialised at %s", db_path)
    return db_path


# ── Headcount queries (aggregated from roster) ─────────────────────────

def fetch_headcount(db_path: str, cia: str, year: int) -> list[dict]:
    """Return headcount per CECO/month for a company/year."""
    lo = year * 100 + 1
    hi = year * 100 + 12
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT centro_costo, year_month, COUNT(DISTINCT empleado) AS headcount "
            "FROM employee_roster "
            "WHERE cia = ? AND year_month BETWEEN ? AND ? "
            "GROUP BY centro_costo, year_month "
            "ORDER BY centro_costo, year_month",
            (cia, lo, hi),
        ).fetchall()
    return [dict(r) for r in rows]


def fetch_headcount_all(db_path: str, cia: str) -> list[dict]:
    """Return headcount per CECO/month for a company (all years)."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT centro_costo, year_month, COUNT(DISTINCT empleado) AS headcount "
            "FROM employee_roster "
            "WHERE cia = ? "
            "GROUP BY centro_costo, year_month "
            "ORDER BY year_month, centro_costo",
            (cia,),
        ).fetchall()
    return [dict(r) for r in rows]


# ── Roster CRUD ─────────────────────────────────────────────────────────

def bulk_upsert_roster(db_path: str, records: list[dict]) -> int:
    """Insert or ignore raw employee roster rows.

    Each dict must have keys: cia, centro_costo, year_month, empleado, nombre.
    Returns the number of rows written.
    """
    if not records:
        return 0
    with _connect(db_path) as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO employee_roster "
            "(cia, centro_costo, year_month, empleado, nombre) "
            "VALUES (?, ?, ?, ?, ?)",
            [(r["cia"], r["centro_costo"], r["year_month"],
              r["empleado"], r.get("nombre", ""))
             for r in records],
        )
    logger.info("Upserted %d roster records", len(records))
    return len(records)


def fetch_roster_detail(
    db_path: str, cia: str, centro_costo: str, year_month: int,
) -> list[dict]:
    """Return individual employees for a specific company/CECO/month."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT empleado, nombre FROM employee_roster "
            "WHERE cia = ? AND centro_costo = ? AND year_month = ? "
            "ORDER BY nombre, empleado",
            (cia, centro_costo, year_month),
        ).fetchall()
    return [dict(r) for r in rows]


def clear_roster(db_path: str) -> None:
    """Delete all rows from employee_roster table."""
    with _connect(db_path) as conn:
        conn.execute("DELETE FROM employee_roster")


def roster_count(db_path: str) -> int:
    """Return total number of raw roster rows."""
    with _connect(db_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM employee_roster").fetchone()[0]
