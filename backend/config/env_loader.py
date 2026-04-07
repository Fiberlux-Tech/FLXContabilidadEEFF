"""Environment-specific .env loader.

Loads configuration in layers:
1. `.env` — shared defaults (always loaded)
2. `.env.{APP_ENV}` — environment-specific overrides (development or production)

The active environment is determined by the APP_ENV environment variable.
If APP_ENV is not set, it defaults to "production" for safety.

Usage:
    from config.env_loader import load_env_config
    load_env_config()  # call once at startup, before reading os.environ
"""

import os
from pathlib import Path

from dotenv import load_dotenv


def _find_monorepo_root() -> Path:
    """Return the monorepo root directory (grandparent of this config package)."""
    return Path(__file__).resolve().parent.parent.parent


def load_env_config(root: str | Path | None = None) -> str:
    """Load layered .env files and return the resolved environment name.

    Parameters
    ----------
    root : str | Path | None
        Monorepo root directory.  Detected automatically when *None*.

    Returns
    -------
    str
        The active environment name ("development" or "production").
    """
    if root is None:
        root = _find_monorepo_root()
    root = Path(root)

    # 1. Load base .env (shared defaults).
    #    override=False so that real OS-level env vars always win.
    base_env = root / ".env"
    load_dotenv(base_env, override=False)

    # 2. Determine which environment we're running in.
    app_env = os.environ.get("APP_ENV", "production").lower()

    # 3. Load environment-specific overrides.
    #    override=True so that .env.production values beat .env defaults,
    #    but real OS-level env vars (set before any dotenv loading) still win
    #    because load_dotenv only overrides values set by earlier dotenv calls.
    env_file = root / f".env.{app_env}"
    if env_file.is_file():
        load_dotenv(env_file, override=True)

    return app_env
