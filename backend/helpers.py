"""Shared response helpers for Flask routes."""

import json

from flask import jsonify


def ok(data):
    """Wrap a successful response in a standard envelope."""
    return jsonify({'status': 'ok', 'data': data})


def error(message, status_code=500):
    """Wrap an error response in a standard envelope."""
    return jsonify({'status': 'error', 'error': message}), status_code


def _row_get(row, key, default=None):
    """sqlite3.Row supports __getitem__ but not .get — this fills the gap."""
    try:
        return row[key]
    except (IndexError, KeyError):
        return default


def user_dict(user):
    """Build a serialisable user dict from a database Row."""
    raw_views = _row_get(user, 'allowed_views', '[]') or '[]'
    try:
        allowed_views = json.loads(raw_views)
    except (json.JSONDecodeError, TypeError):
        allowed_views = []
    return {
        'id': user['id'],
        'username': user['username'],
        'display_name': user['display_name'] or user['username'],
        'is_admin': bool(_row_get(user, 'is_admin', 0)),
        'allowed_views': allowed_views,
    }
