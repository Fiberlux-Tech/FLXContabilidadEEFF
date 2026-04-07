import logging
from collections.abc import Generator
from contextlib import contextmanager
from queue import Queue, Empty

import pyodbc

from config.settings import get_config, DatabaseConfig
from config.exceptions import ConfigurationError


logger = logging.getLogger("plantillas.db")

# Enable pyodbc's built-in ODBC connection pooling (off by default on Linux)
pyodbc.pooling = True


def _build_conn_str(db_cfg: DatabaseConfig) -> str:
    missing = []
    for attr in ("driver", "server", "database", "uid", "pwd"):
        if not getattr(db_cfg, attr):
            missing.append(f"DB_{attr.upper()}")
    if missing:
        raise ConfigurationError(
            f"Missing required database environment variables: {', '.join(missing)}. "
            "Check your .env file."
        )

    return (
        f"DRIVER={{{db_cfg.driver}}};"
        f"SERVER={db_cfg.server};"
        f"DATABASE={db_cfg.database};"
        f"UID={db_cfg.uid};"
        f"PWD={db_cfg.pwd};"
        f"Encrypt={db_cfg.encrypt};"
        f"TrustServerCertificate={db_cfg.trust_cert};"
    )


# ── Connection pool ──────────────────────────────────────────────────────

_conn_str: str | None = None
_pool: Queue[pyodbc.Connection] | None = None


def _get_pool() -> Queue[pyodbc.Connection]:
    """Lazily create the connection pool with configured size."""
    global _pool
    if _pool is None:
        cfg = get_config().db
        _pool = Queue(maxsize=cfg.pool_size)
    return _pool


def _get_conn_str() -> str:
    """Lazily build and cache the connection string."""
    global _conn_str
    if _conn_str is None:
        cfg = get_config().db
        _conn_str = _build_conn_str(cfg)
    return _conn_str


def _new_conn() -> pyodbc.Connection:
    """Create a fresh database connection."""
    cfg = get_config().db
    conn = pyodbc.connect(_get_conn_str(), timeout=cfg.connect_timeout, autocommit=True)
    conn.timeout = cfg.query_timeout
    return conn


def _is_alive(conn: pyodbc.Connection) -> bool:
    """Quick check that a pooled connection is still usable."""
    try:
        conn.execute("SELECT 1")
        return True
    except (pyodbc.Error, Exception):
        return False


@contextmanager
def connect() -> Generator[pyodbc.Connection]:
    """Grab a connection from the pool (or create one), yield it, return it.

    If the pooled connection is stale, it's discarded and a new one is created.
    On exit the connection is returned to the pool if there's room; otherwise
    it's closed outright.
    """
    conn = None

    # Try to grab an existing connection from the pool
    pool = _get_pool()
    try:
        conn = pool.get_nowait()
        if not _is_alive(conn):
            try:
                conn.close()
            except Exception:
                pass
            conn = None
    except Empty:
        pass

    if conn is None:
        conn = _new_conn()

    try:
        yield conn
    except Exception:
        # On error, close the connection rather than returning it to the pool
        try:
            conn.close()
        except Exception:
            pass
        raise
    else:
        # Return to pool if there's room, otherwise close
        try:
            pool.put_nowait(conn)
        except Exception:
            conn.close()
