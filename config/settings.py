"""Centralized configuration — single point of truth for all environment variables."""

import functools
import os
from dataclasses import dataclass, field

from config.exceptions import ConfigurationError

_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def _parse_positive_int(value: str, name: str) -> int:
    """Parse a string as a positive integer, raising ConfigurationError on failure."""
    try:
        n = int(value)
    except (ValueError, TypeError):
        raise ConfigurationError(f"{name} must be a valid integer, got: {value!r}")
    if n <= 0:
        raise ConfigurationError(f"{name} must be positive, got: {n}")
    return n


@dataclass(frozen=True)
class DatabaseConfig:
    driver: str = ""
    server: str = ""
    database: str = ""
    uid: str = ""
    pwd: str = ""
    connect_timeout: int = 30
    query_timeout: int = 120
    pool_size: int = 8
    fetch_max_workers: int = 5
    encrypt: str = "yes"
    trust_cert: str = "no"


@dataclass(frozen=True)
class Config:
    log_level: str = "INFO"
    output_dir: str = "."
    strict_bs_balance: bool = False  # True = raise on BS imbalance; False = warn only
    db: DatabaseConfig = field(default_factory=DatabaseConfig)

    def __post_init__(self):
        if self.log_level not in _VALID_LOG_LEVELS:
            raise ConfigurationError(
                f"LOG_LEVEL must be one of {_VALID_LOG_LEVELS}, got: {self.log_level!r}"
            )
        if not self.output_dir:
            raise ConfigurationError("OUTPUT_DIR must not be empty")


@functools.lru_cache(maxsize=1)
def get_config() -> Config:
    """Build Config from environment variables (call after load_dotenv)."""
    return Config(
        log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        output_dir=os.environ.get("OUTPUT_DIR", "."),
        strict_bs_balance=os.environ.get("STRICT_BS_BALANCE", "").lower() in ("1", "true", "yes"),
        db=DatabaseConfig(
            driver=os.environ.get("DB_DRIVER", ""),
            server=os.environ.get("DB_SERVER", ""),
            database=os.environ.get("DB_DATABASE", ""),
            uid=os.environ.get("DB_UID", ""),
            pwd=os.environ.get("DB_PWD", ""),
            connect_timeout=_parse_positive_int(os.environ.get("DB_CONNECT_TIMEOUT", "30"), "DB_CONNECT_TIMEOUT"),
            query_timeout=_parse_positive_int(os.environ.get("DB_QUERY_TIMEOUT", "120"), "DB_QUERY_TIMEOUT"),
            pool_size=_parse_positive_int(os.environ.get("DB_POOL_SIZE", "8"), "DB_POOL_SIZE"),
            fetch_max_workers=_parse_positive_int(os.environ.get("FETCH_MAX_WORKERS", "5"), "FETCH_MAX_WORKERS"),
            encrypt=os.environ.get("DB_ENCRYPT", "yes"),
            trust_cert=os.environ.get("DB_TRUST_CERT", "no"),
        ),
    )
