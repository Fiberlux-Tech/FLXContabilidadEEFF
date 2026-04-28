"""Admin-only routes — user management UI backend.

CRUD scope is intentionally limited: list users and PATCH their permissions.
Creation, password resets, and deletion stay in the CLI script
(`backend/scripts/manage_users.py`) to keep the web surface small.
"""

import json
import logging

from flask import Blueprint, request, session

from auth import admin_required, get_db
from config.views import ALL_VIEW_IDS
from helpers import ok, error


admin_bp = Blueprint('admin', __name__)
logger = logging.getLogger('flxcontabilidad.admin')


def _serialize_user(row) -> dict:
    """Render a users row for the admin UI (excludes password_hash)."""
    try:
        allowed = json.loads(row['allowed_views'] or '[]')
    except (json.JSONDecodeError, TypeError):
        allowed = []
    return {
        'id': row['id'],
        'username': row['username'],
        'display_name': row['display_name'] or row['username'],
        'is_admin': bool(row['is_admin']),
        'allowed_views': allowed,
        'created_at': row['created_at'],
    }


@admin_bp.route('/users', methods=['GET'])
@admin_required
def list_users():
    """Return all users with their permissions."""
    db = get_db()
    rows = db.execute(
        "SELECT id, username, display_name, created_at, is_admin, allowed_views "
        "FROM users ORDER BY id"
    ).fetchall()
    return ok({'users': [_serialize_user(r) for r in rows]})


@admin_bp.route('/users/<int:user_id>', methods=['PATCH'])
@admin_required
def update_user(user_id: int):
    """Update is_admin and/or allowed_views for a user.

    Body: { "is_admin"?: bool, "allowed_views"?: [str, ...] }

    Safety rails (enforced inside a BEGIN IMMEDIATE transaction):
    - You cannot demote yourself.
    - You cannot remove the last remaining admin.
    """
    body = request.get_json(silent=True) or {}
    actor_id = session['user_id']

    # Validate inputs up-front
    new_is_admin = body.get('is_admin')
    if new_is_admin is not None and not isinstance(new_is_admin, bool):
        return error('is_admin debe ser booleano', 400)

    new_allowed_views = body.get('allowed_views')
    if new_allowed_views is not None:
        if not isinstance(new_allowed_views, list) or not all(isinstance(v, str) for v in new_allowed_views):
            return error('allowed_views debe ser lista de strings', 400)
        unknown = set(new_allowed_views) - ALL_VIEW_IDS
        if unknown:
            return error(f'Vistas desconocidas: {sorted(unknown)}', 400)
        # admin_users is admin-only — silently strip if a non-admin is being granted it
        new_allowed_views = [v for v in new_allowed_views if v != 'admin_users']

    if new_is_admin is None and new_allowed_views is None:
        return error('Nada que actualizar', 400)

    db = get_db()
    try:
        db.execute('BEGIN IMMEDIATE')

        target = db.execute(
            "SELECT id, username, is_admin, allowed_views FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if target is None:
            db.execute('ROLLBACK')
            return error('Usuario no encontrado', 404)

        # Self-demote guard
        if (
            new_is_admin is False
            and user_id == actor_id
            and bool(target['is_admin'])
        ):
            db.execute('ROLLBACK')
            return error('No puedes quitarte tu propio acceso de administrador', 400)

        # Last-admin guard
        if new_is_admin is False and bool(target['is_admin']):
            other_admins = db.execute(
                "SELECT COUNT(*) FROM users WHERE is_admin = 1 AND id != ?",
                (user_id,),
            ).fetchone()[0]
            if other_admins == 0:
                db.execute('ROLLBACK')
                return error('No puedes eliminar al unico administrador', 400)

        # Build the change payload + execute
        changes = {}
        if new_is_admin is not None and bool(target['is_admin']) != new_is_admin:
            db.execute(
                "UPDATE users SET is_admin = ? WHERE id = ?",
                (1 if new_is_admin else 0, user_id),
            )
            changes['is_admin'] = {'from': bool(target['is_admin']), 'to': new_is_admin}

        if new_allowed_views is not None:
            try:
                old_views = json.loads(target['allowed_views'] or '[]')
            except (json.JSONDecodeError, TypeError):
                old_views = []
            sorted_new = sorted(set(new_allowed_views))
            if sorted(old_views) != sorted_new:
                db.execute(
                    "UPDATE users SET allowed_views = ? WHERE id = ?",
                    (json.dumps(sorted_new), user_id),
                )
                changes['allowed_views'] = {'from': sorted(old_views), 'to': sorted_new}

        if changes:
            db.execute(
                "INSERT INTO user_audit_log (actor_user_id, target_user_id, change_json) "
                "VALUES (?, ?, ?)",
                (actor_id, user_id, json.dumps(changes)),
            )

        db.commit()
    except Exception:
        db.execute('ROLLBACK')
        logger.exception("admin update_user failed for user_id=%s", user_id)
        raise

    # Return the updated row
    updated = db.execute(
        "SELECT id, username, display_name, created_at, is_admin, allowed_views "
        "FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    return ok(_serialize_user(updated))
