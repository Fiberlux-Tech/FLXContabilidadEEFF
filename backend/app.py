"""Flask application — lightweight backend with SQLite auth."""

import logging
import os
import sys

# Ensure monorepo root is on sys.path so bare `from config.…` imports work.
_monorepo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _monorepo_root not in sys.path:
    sys.path.insert(0, _monorepo_root)

from config.env_loader import load_env_config

# Load layered .env → .env.{APP_ENV} configuration
_app_env = load_env_config(_monorepo_root)

from flask import Flask, request
from flask_cors import CORS

from auth import auth_bp, init_db
from constants import DEFAULT_DB_PATH


def create_app():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    app = Flask(__name__)

    secret_key = os.environ.get('SECRET_KEY')
    if not secret_key:
        raise RuntimeError(
            'SECRET_KEY environment variable is not set. '
            'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
        )
    app.secret_key = secret_key

    # Session cookie security — explicit even though these match Flask defaults,
    # so intent is documented and future changes don't regress.
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    # SESSION_COOKIE_SECURE intentionally False — app served over plain HTTP on internal network

    # CORS
    origins_raw = os.environ.get('CORS_ALLOWED_ORIGINS', 'http://localhost:5173')
    origins = [o.strip() for o in origins_raw.split(',') if o.strip()]
    CORS(app, origins=origins, supports_credentials=True)

    # SQLite DB path — resolve relative paths from monorepo root
    db_path = os.environ.get('SQLITE_DB_PATH', DEFAULT_DB_PATH)
    if not os.path.isabs(db_path):
        db_path = os.path.join(_monorepo_root, db_path)
    # Ensure the directory for the SQLite DB exists
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    app.config['SQLITE_DB_PATH'] = db_path

    # Initialize auth DB
    init_db(app)

    # Initialize headcount DB (SQLite, separate from auth)
    from data.headcount_db import init_headcount_db
    hc_db_path = os.environ.get(
        'HEADCOUNT_DB_PATH',
        os.path.join(_monorepo_root, 'data', 'headcount.db'),
    )
    app.config['HEADCOUNT_DB_PATH'] = init_headcount_db(hc_db_path)

    # Register blueprints
    app.register_blueprint(auth_bp, url_prefix='/auth')

    # Add monorepo root and services/ to Python path.
    # Monorepo root allows `from config.company import ...`
    # Services dir allows bare imports used inside the pipeline (`from config.xxx`)
    services_dir = os.path.join(_monorepo_root, 'services')
    for p in (_monorepo_root, services_dir):
        if p not in sys.path:
            sys.path.insert(0, p)

    from routes import api_bp
    app.register_blueprint(api_bp, url_prefix='/api')

    # Response size logging for API endpoints
    _api_logger = logging.getLogger('flxcontabilidad.response')

    @app.after_request
    def log_response_size(response):
        if request.path.startswith('/api/'):
            size = response.content_length or len(response.get_data())
            _api_logger.info(
                "%s %s — %d bytes, status %d",
                request.method, request.path, size, response.status_code,
            )
        return response

    return app


app = create_app()
