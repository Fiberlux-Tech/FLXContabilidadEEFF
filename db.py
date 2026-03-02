import logging
from collections.abc import Generator
from contextlib import contextmanager

import pyodbc

from config import get_config, DatabaseConfig
from exceptions import ConfigurationError


logger = logging.getLogger("plantillas.db")


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


# ── Connection helper ─────────────────────────────────────────────────────

_conn_str: str | None = None


def _get_conn_str() -> str:
    """Lazily build and cache the connection string."""
    global _conn_str
    if _conn_str is None:
        cfg = get_config().db
        _conn_str = _build_conn_str(cfg)
    return _conn_str


@contextmanager
def connect() -> Generator[pyodbc.Connection]:
    """Create a database connection, yield it, and close on exit."""
    cfg = get_config().db
    conn = pyodbc.connect(_get_conn_str(), timeout=cfg.connect_timeout)
    conn.timeout = cfg.query_timeout
    try:
        yield conn
    finally:
        conn.close()


def close_pool() -> None:
    """No-op kept for backward compatibility with existing callers."""
    pass
