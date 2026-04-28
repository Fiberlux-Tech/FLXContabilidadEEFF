"""Flask application — lightweight backend with SQLite auth."""

import logging
import os
import sys

# Ensure backend dir is on sys.path so bare `from config.…` imports work.
_backend_dir = os.path.abspath(os.path.dirname(__file__))
_monorepo_root = os.path.abspath(os.path.join(_backend_dir, '..'))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from config.env_loader import load_env_config

# Load layered .env → .env.{APP_ENV} configuration
_app_env = load_env_config(_monorepo_root)

import orjson
from flask import Flask, request
from flask.json.provider import JSONProvider
from flask_cors import CORS

from auth import auth_bp, init_db
from constants import DEFAULT_DB_PATH


class OrjsonProvider(JSONProvider):
    """Flask JSON provider backed by orjson.

    ~3-5x faster than stdlib json on the large nested dicts our P&L sections
    return. _sanitize_value (in services/data_service.py) already converts
    numpy types and NaN→None upstream, so the OPT flags below are defensive.
    """
    _OPTS = orjson.OPT_NON_STR_KEYS | orjson.OPT_SERIALIZE_NUMPY

    def dumps(self, obj, **kwargs):
        return orjson.dumps(obj, option=self._OPTS).decode("utf-8")

    def loads(self, s, **kwargs):
        if isinstance(s, str):
            s = s.encode("utf-8")
        return orjson.loads(s)


def create_app():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    app = Flask(__name__)
    app.json = OrjsonProvider(app)

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
    # Per-environment cookie name so prod (port 80) and staging (port 8081) on the
    # same host don't clobber each other's sessions (browsers key cookies by
    # domain only, ignoring port).
    app.config['SESSION_COOKIE_NAME'] = os.environ.get('SESSION_COOKIE_NAME', 'session')

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
        os.path.join(_backend_dir, 'data', 'headcount.db'),
    )
    app.config['HEADCOUNT_DB_PATH'] = init_headcount_db(hc_db_path)

    # Register blueprints
    app.register_blueprint(auth_bp, url_prefix='/auth')

    # Add services/ to Python path so bare imports inside the pipeline work
    # (`from data_service import …`, `from pipeline import …`)
    services_dir = os.path.join(_backend_dir, 'services')
    if services_dir not in sys.path:
        sys.path.insert(0, services_dir)

    from routes import api_bp
    app.register_blueprint(api_bp, url_prefix='/api')

    from admin_routes import admin_bp
    app.register_blueprint(admin_bp, url_prefix='/api/admin')

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
