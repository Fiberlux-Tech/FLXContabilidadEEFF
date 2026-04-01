"""SQLite-backed storage for headcount-per-CECO data."""

import logging
import os
import sqlite3

logger = logging.getLogger("flxcontabilidad.headcount_db")

_DEFAULT_DB = os.path.join(os.path.dirname(__file__), "headcount.db")

_CREATE_TABLE = """\
CREATE TABLE IF NOT EXISTS headcount (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    cia          TEXT    NOT NULL,
    centro_costo TEXT    NOT NULL,
    year_month   INTEGER NOT NULL,
    headcount    INTEGER NOT NULL,
    updated_at   TEXT    DEFAULT (datetime('now')),
    UNIQUE(cia, centro_costo, year_month),
    CHECK(headcount > 0),
    CHECK(year_month >= 202001 AND year_month <= 209912)
);
"""

_CREATE_INDEX = """\
CREATE INDEX IF NOT EXISTS idx_headcount_cia_ym
    ON headcount(cia, year_month);
"""


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_headcount_db(db_path: str | None = None) -> str:
    """Create the headcount table + index if they don't exist.

    Returns the resolved db_path so callers can store it.
    """
    db_path = db_path or _DEFAULT_DB
    with _connect(db_path) as conn:
        conn.execute(_CREATE_TABLE)
        conn.execute(_CREATE_INDEX)
    logger.info("Headcount DB initialised at %s", db_path)
    return db_path


def fetch_headcount(db_path: str, cia: str, year: int) -> list[dict]:
    """Return all headcount rows for a company/year."""
    lo = year * 100 + 1
    hi = year * 100 + 12
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT centro_costo, year_month, headcount "
            "FROM headcount WHERE cia = ? AND year_month BETWEEN ? AND ? "
            "ORDER BY centro_costo, year_month",
            (cia, lo, hi),
        ).fetchall()
    return [dict(r) for r in rows]


def fetch_headcount_all(db_path: str, cia: str) -> list[dict]:
    """Return all headcount rows for a company (all years)."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT centro_costo, year_month, headcount "
            "FROM headcount WHERE cia = ? ORDER BY year_month, centro_costo",
            (cia,),
        ).fetchall()
    return [dict(r) for r in rows]


def bulk_upsert(db_path: str, records: list[dict]) -> int:
    """Insert or replace headcount records.  Skips rows with headcount <= 0.

    Each dict must have keys: cia, centro_costo, year_month, headcount.
    Returns the number of rows actually written.
    """
    valid = [
        r for r in records
        if isinstance(r.get("headcount"), (int, float)) and r["headcount"] > 0
    ]
    if not valid:
        return 0
    with _connect(db_path) as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO headcount (cia, centro_costo, year_month, headcount, updated_at) "
            "VALUES (?, ?, ?, ?, datetime('now'))",
            [(r["cia"], r["centro_costo"], r["year_month"], int(r["headcount"])) for r in valid],
        )
    logger.info("Upserted %d headcount records", len(valid))
    return len(valid)


def delete_headcount(db_path: str, cia: str, centro_costo: str, year_month: int) -> bool:
    """Delete a single headcount entry. Returns True if a row was deleted."""
    with _connect(db_path) as conn:
        cur = conn.execute(
            "DELETE FROM headcount WHERE cia = ? AND centro_costo = ? AND year_month = ?",
            (cia, centro_costo, year_month),
        )
    return cur.rowcount > 0
