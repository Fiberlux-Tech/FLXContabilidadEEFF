"""Shared response helpers for Flask routes."""

from flask import jsonify


def ok(data):
    """Wrap a successful response in a standard envelope."""
    return jsonify({'status': 'ok', 'data': data})


def error(message, status_code=500):
    """Wrap an error response in a standard envelope."""
    return jsonify({'status': 'error', 'error': message}), status_code


def user_dict(user):
    """Build a serialisable user dict from a database Row."""
    return {
        'id': user['id'],
        'username': user['username'],
        'display_name': user['display_name'] or user['username'],
    }
