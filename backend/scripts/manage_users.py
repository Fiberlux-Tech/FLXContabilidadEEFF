#!/usr/bin/env python3
"""CLI for user management — create, delete, list, set-password, set-admin.

Web UI handles is_admin + allowed_views editing for existing users; this
script is the only way to create new users, delete users, or reset
passwords. Reads SQLITE_DB_PATH from .env or env var, falling back to the
hardcoded DEFAULT_DB_PATH.

Run from the repo root:
    python backend/scripts/manage_users.py <command> [args...]
"""

import argparse
import getpass
import json
import os
import sqlite3
import sys

# Path setup: this script lives at backend/scripts/manage_users.py
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.abspath(os.path.join(_THIS_DIR, '..'))
_REPO_ROOT = os.path.abspath(os.path.join(_BACKEND_DIR, '..'))
sys.path.insert(0, _BACKEND_DIR)

# Load .env / .env.{APP_ENV} so SQLITE_DB_PATH is picked up the same way
# the Flask app loads it.
from config.env_loader import load_env_config  # noqa: E402
load_env_config(_REPO_ROOT)

from auth import hash_password, ensure_users_table  # noqa: E402
from constants import DEFAULT_DB_PATH  # noqa: E402


def _db_path() -> str:
    path = os.environ.get('SQLITE_DB_PATH', DEFAULT_DB_PATH)
    if not os.path.isabs(path):
        path = os.path.join(_REPO_ROOT, path)
    return path


def _connect() -> sqlite3.Connection:
    path = _db_path()
    ensure_users_table(path)  # idempotent migration
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def cmd_list(args) -> int:
    conn = _connect()
    rows = conn.execute(
        "SELECT id, username, display_name, is_admin, allowed_views, created_at "
        "FROM users ORDER BY id"
    ).fetchall()
    if not rows:
        print('(no users)')
        return 0
    print(f'{"id":>3}  {"username":<20} {"display_name":<25} admin  views  created')
    print('-' * 80)
    for r in rows:
        try:
            n_views = len(json.loads(r['allowed_views'] or '[]'))
        except (json.JSONDecodeError, TypeError):
            n_views = 0
        admin_mark = 'YES' if r['is_admin'] else '-'
        print(f'{r["id"]:>3}  {r["username"]:<20} {(r["display_name"] or ""):<25} {admin_mark:<5}  {n_views:>5}  {r["created_at"]}')
    return 0


def cmd_create(args) -> int:
    conn = _connect()
    existing = conn.execute("SELECT id FROM users WHERE username = ?", (args.username,)).fetchone()
    if existing:
        print(f'error: username already exists: {args.username}', file=sys.stderr)
        return 1
    pw1 = getpass.getpass('Password: ')
    pw2 = getpass.getpass('Repeat:   ')
    if pw1 != pw2:
        print('error: passwords do not match', file=sys.stderr)
        return 1
    if len(pw1) < 8:
        print('error: password must be at least 8 characters', file=sys.stderr)
        return 1
    conn.execute(
        "INSERT INTO users (username, password_hash, display_name, is_admin, allowed_views) "
        "VALUES (?, ?, ?, 0, '[]')",
        (args.username, hash_password(pw1), args.display_name),
    )
    conn.commit()
    print(f'created user {args.username!r} (no views granted — use the admin UI to assign access)')
    return 0


def cmd_set_password(args) -> int:
    conn = _connect()
    user = conn.execute("SELECT id FROM users WHERE username = ?", (args.username,)).fetchone()
    if user is None:
        print(f'error: no such user: {args.username}', file=sys.stderr)
        return 1
    pw1 = getpass.getpass('New password: ')
    pw2 = getpass.getpass('Repeat:       ')
    if pw1 != pw2:
        print('error: passwords do not match', file=sys.stderr)
        return 1
    if len(pw1) < 8:
        print('error: password must be at least 8 characters', file=sys.stderr)
        return 1
    conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(pw1), user['id']))
    conn.commit()
    print(f'password updated for {args.username!r}')
    return 0


def cmd_delete(args) -> int:
    conn = _connect()
    user = conn.execute("SELECT id, is_admin FROM users WHERE username = ?", (args.username,)).fetchone()
    if user is None:
        print(f'error: no such user: {args.username}', file=sys.stderr)
        return 1
    if user['is_admin']:
        other_admins = conn.execute(
            "SELECT COUNT(*) FROM users WHERE is_admin = 1 AND id != ?", (user['id'],)
        ).fetchone()[0]
        if other_admins == 0:
            print('error: cannot delete the only remaining admin', file=sys.stderr)
            return 1
    confirm = input(f'Type the username again to confirm deletion of {args.username!r}: ')
    if confirm != args.username:
        print('aborted')
        return 1
    conn.execute("DELETE FROM users WHERE id = ?", (user['id'],))
    conn.commit()
    print(f'deleted user {args.username!r}')
    return 0


def cmd_set_admin(args) -> int:
    conn = _connect()
    user = conn.execute("SELECT id, is_admin FROM users WHERE username = ?", (args.username,)).fetchone()
    if user is None:
        print(f'error: no such user: {args.username}', file=sys.stderr)
        return 1
    new_value = 1 if args.value in ('1', 'true', 'yes', 'on') else 0
    if not new_value and user['is_admin']:
        other_admins = conn.execute(
            "SELECT COUNT(*) FROM users WHERE is_admin = 1 AND id != ?", (user['id'],)
        ).fetchone()[0]
        if other_admins == 0:
            print('error: cannot demote the only remaining admin', file=sys.stderr)
            return 1
    conn.execute("UPDATE users SET is_admin = ? WHERE id = ?", (new_value, user['id']))
    conn.commit()
    print(f'set is_admin={new_value} for {args.username!r}')
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description='User management for FLXContabilidad')
    parser.add_argument('--db', help='Override SQLITE_DB_PATH for this invocation')
    sub = parser.add_subparsers(dest='cmd', required=True)

    sub.add_parser('list', help='List all users')

    p = sub.add_parser('create', help='Create a new user (no views granted by default)')
    p.add_argument('username')
    p.add_argument('display_name')

    p = sub.add_parser('set-password', help='Reset a user password')
    p.add_argument('username')

    p = sub.add_parser('delete', help='Delete a user (requires confirmation)')
    p.add_argument('username')

    p = sub.add_parser('set-admin', help='Toggle is_admin for a user')
    p.add_argument('username')
    p.add_argument('value', choices=['0', '1', 'true', 'false', 'yes', 'no', 'on', 'off'])

    args = parser.parse_args()
    if args.db:
        os.environ['SQLITE_DB_PATH'] = args.db

    handlers = {
        'list': cmd_list,
        'create': cmd_create,
        'set-password': cmd_set_password,
        'delete': cmd_delete,
        'set-admin': cmd_set_admin,
    }
    return handlers[args.cmd](args)


if __name__ == '__main__':
    sys.exit(main())
