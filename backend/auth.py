"""Lightweight SQLite authentication — session-based, no signup endpoint."""

import json
import os
import sqlite3
import time
from collections import defaultdict
from functools import wraps
from threading import Lock

import bcrypt

from flask import Blueprint, request, session, current_app, g
from helpers import ok, error, user_dict
from config.views import ALL_VIEW_IDS


auth_bp = Blueprint('auth', __name__)

# ---------------------------------------------------------------------------
# In-memory rate limiter for login endpoint
# ---------------------------------------------------------------------------
_MAX_ATTEMPTS = 5           # max failed attempts before lockout
_LOCKOUT_WINDOW = 300       # seconds (5 minutes)

_failed_attempts: dict[str, list[float]] = defaultdict(list)
_lock = Lock()


def _prune_old_attempts(ip: str) -> None:
    """Remove attempts outside the lockout window. Caller must hold _lock."""
    now = time.monotonic()
    _failed_attempts[ip] = [t for t in _failed_attempts[ip] if now - t < _LOCKOUT_WINDOW]


def _is_rate_limited(ip: str) -> bool:
    """Return True if *ip* has exceeded the failed-login threshold."""
    with _lock:
        _prune_old_attempts(ip)
        return len(_failed_attempts[ip]) >= _MAX_ATTEMPTS


def _record_failed_attempt(ip: str) -> None:
    """Record a failed login attempt for *ip*."""
    with _lock:
        _prune_old_attempts(ip)
        _failed_attempts[ip].append(time.monotonic())


def _clear_attempts(ip: str) -> None:
    """Clear failed attempts for *ip* after a successful login."""
    with _lock:
        _failed_attempts.pop(ip, None)


def get_db():
    """Get SQLite connection for current request."""
    if 'db' not in g:
        g.db = sqlite3.connect(current_app.config['SQLITE_DB_PATH'])
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()


_USERS_DDL = '''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        display_name TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_admin INTEGER NOT NULL DEFAULT 0,
        allowed_views TEXT NOT NULL DEFAULT '[]'
    )
'''

_AUDIT_DDL = '''
    CREATE TABLE IF NOT EXISTS user_audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        actor_user_id INTEGER NOT NULL,
        target_user_id INTEGER NOT NULL,
        change_json TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
'''

# Username seeded as admin during migration. Idempotent; no-op if absent.
_SEED_ADMIN_USERNAME = 'admin'


def ensure_users_table(db_path: str) -> None:
    """Create users table if it doesn't exist (standalone, no Flask needed).

    Also runs idempotent migrations: adds is_admin/allowed_views columns to
    pre-existing tables, grandfathers existing users with full access on
    first migration, creates the user_audit_log table, and seeds the admin
    flag for the canonical admin username.
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(_USERS_DDL)
        conn.execute(_AUDIT_DDL)

        cols = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
        added_allowed_views = False

        if 'is_admin' not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
        if 'allowed_views' not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN allowed_views TEXT NOT NULL DEFAULT '[]'")
            added_allowed_views = True

        # Grandfather: on first migration, give every existing user full access
        # so the rollout doesn't lock anyone out. New users created post-migration
        # default to '[]' and must be granted access explicitly.
        if added_allowed_views:
            all_ids_json = json.dumps(sorted(ALL_VIEW_IDS))
            conn.execute(
                "UPDATE users SET allowed_views = ? WHERE allowed_views = '[]'",
                (all_ids_json,),
            )

        # Seed admin (idempotent — no-op if username doesn't exist)
        conn.execute(
            "UPDATE users SET is_admin = 1 WHERE username = ?",
            (_SEED_ADMIN_USERNAME,),
        )

        conn.commit()
    finally:
        conn.close()


def init_db(app):
    """Create users table and register Flask teardown."""
    ensure_users_table(app.config['SQLITE_DB_PATH'])
    app.teardown_appcontext(close_db)


def hash_password(password: str) -> str:
    """Hash password using bcrypt."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def check_password(password: str, password_hash: str) -> bool:
    """Verify a password against a bcrypt hash."""
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def login_required(f):
    """Decorator to require authentication."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return error('Authentication required', 401)
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """Decorator to require admin privileges (reads session — set at login)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return error('Authentication required', 401)
        if not session.get('is_admin'):
            return error('Forbidden', 403)
        return f(*args, **kwargs)
    return decorated


def view_required(view_id: str):
    """Decorator factory: require admin OR view_id in session['allowed_views']."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if 'user_id' not in session:
                return error('Authentication required', 401)
            if session.get('is_admin'):
                return f(*args, **kwargs)
            if view_id not in session.get('allowed_views', []):
                return error('Forbidden', 403)
            return f(*args, **kwargs)
        return decorated
    return decorator


def any_view_required(view_ids):
    """Decorator factory: pass if user has access to ANY of the listed views.

    Used for endpoints that span sections (e.g. /api/data/load, exports).
    """
    view_ids = list(view_ids)
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if 'user_id' not in session:
                return error('Authentication required', 401)
            if session.get('is_admin'):
                return f(*args, **kwargs)
            allowed = set(session.get('allowed_views', []))
            if not allowed.intersection(view_ids):
                return error('Forbidden', 403)
            return f(*args, **kwargs)
        return decorated
    return decorator


def require_view_or_403(view_id: str):
    """Inline helper for handlers that resolve the view from request body.

    Returns None if access allowed, otherwise a Flask error response that
    callers should `return` immediately.
    """
    if 'user_id' not in session:
        return error('Authentication required', 401)
    if session.get('is_admin'):
        return None
    if view_id not in session.get('allowed_views', []):
        return error('Forbidden', 403)
    return None


def _set_session_permissions(user_row) -> None:
    """Populate session with cached permissions from a user row."""
    session['is_admin'] = bool(user_row['is_admin'])
    try:
        session['allowed_views'] = json.loads(user_row['allowed_views'] or '[]')
    except (json.JSONDecodeError, TypeError):
        session['allowed_views'] = []


@auth_bp.route('/login', methods=['POST'])
def login():
    client_ip = request.remote_addr or '0.0.0.0'

    if _is_rate_limited(client_ip):
        return error('Too many failed login attempts. Please try again later.', 429)

    data = request.get_json()
    if not data:
        return error('Missing request body', 400)

    username = data.get('username', '').strip()
    password = data.get('password', '')

    if not username or not password:
        return error('Username and password are required', 400)

    db = get_db()
    user = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()

    if user is None:
        _record_failed_attempt(client_ip)
        return error('Invalid credentials', 401)

    if not check_password(password, user['password_hash']):
        _record_failed_attempt(client_ip)
        return error('Invalid credentials', 401)

    _clear_attempts(client_ip)
    session['user_id'] = user['id']
    session['username'] = user['username']
    _set_session_permissions(user)

    return ok(user_dict(user))


@auth_bp.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return ok({'message': 'Logged out'})


@auth_bp.route('/me', methods=['GET'])
def me():
    if 'user_id' not in session:
        return error('Not authenticated', 401)

    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()

    if user is None:
        session.clear()
        return error('User not found', 401)

    # Refresh cached permissions on /me — picks up admin-side changes after re-login.
    _set_session_permissions(user)

    return ok({'is_authenticated': True, 'user': user_dict(user)})
