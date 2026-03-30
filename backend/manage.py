"""CLI tool to manage users (create, list, delete)."""

import argparse
import getpass
import os
import sqlite3
import sys

_monorepo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _monorepo_root not in sys.path:
    sys.path.insert(0, _monorepo_root)

from config.env_loader import load_env_config
from auth import hash_password, ensure_users_table

load_env_config(_monorepo_root)


def _resolve_db_path():
    monorepo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    db_path = os.environ.get('SQLITE_DB_PATH', './backend/users.db')
    if not os.path.isabs(db_path):
        db_path = os.path.join(monorepo_root, db_path)
    return db_path


def _connect_db():
    """Open a standalone SQLite connection (no Flask context needed)."""
    conn = sqlite3.connect(_resolve_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def _prompt_password():
    """Prompt for password interactively with confirmation."""
    password = getpass.getpass("Password: ")
    if not password:
        print("Error: password cannot be empty.")
        sys.exit(1)
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("Error: passwords do not match.")
        sys.exit(1)
    return password


def create_user(args):
    if not args.password:
        args.password = _prompt_password()

    # Ensure table exists before inserting
    ensure_users_table(_resolve_db_path())
    db = _connect_db()

    password_hash = hash_password(args.password)

    try:
        db.execute(
            'INSERT INTO users (username, password_hash, display_name) VALUES (?, ?, ?)',
            (args.username, password_hash, args.display_name or args.username)
        )
        db.commit()
        print(f"User '{args.username}' created successfully.")
    except sqlite3.IntegrityError:
        print(f"Error: User '{args.username}' already exists.")
        sys.exit(1)
    finally:
        db.close()


def list_users(args):
    db = _connect_db()
    users = db.execute('SELECT id, username, display_name, created_at FROM users').fetchall()
    if not users:
        print("No users found.")
        return
    print(f"{'ID':<5} {'Username':<20} {'Display Name':<25} {'Created'}")
    print("-" * 75)
    for u in users:
        print(f"{u['id']:<5} {u['username']:<20} {u['display_name'] or '':<25} {u['created_at']}")
    db.close()


def delete_user(args):
    db = _connect_db()
    cursor = db.execute('DELETE FROM users WHERE username = ?', (args.username,))
    db.commit()
    if cursor.rowcount > 0:
        print(f"User '{args.username}' deleted.")
    else:
        print(f"User '{args.username}' not found.")
    db.close()


def reset_password(args):
    if not args.password:
        args.password = _prompt_password()

    db = _connect_db()
    password_hash = hash_password(args.password)
    cursor = db.execute(
        'UPDATE users SET password_hash = ? WHERE username = ?',
        (password_hash, args.username)
    )
    db.commit()
    if cursor.rowcount > 0:
        print(f"Password reset for '{args.username}'.")
    else:
        print(f"User '{args.username}' not found.")
    db.close()


def main():
    parser = argparse.ArgumentParser(description='Manage users for FLXContabilidad')
    sub = parser.add_subparsers(dest='command')

    # create-user
    p_create = sub.add_parser('create-user', help='Create a new user')
    p_create.add_argument('--username', required=True)
    p_create.add_argument('--password', default=None, help='Omit to enter interactively')
    p_create.add_argument('--display-name')
    p_create.set_defaults(func=create_user)

    # list-users
    p_list = sub.add_parser('list-users', help='List all users')
    p_list.set_defaults(func=list_users)

    # delete-user
    p_del = sub.add_parser('delete-user', help='Delete a user')
    p_del.add_argument('--username', required=True)
    p_del.set_defaults(func=delete_user)

    # reset-password
    p_reset = sub.add_parser('reset-password', help='Reset user password')
    p_reset.add_argument('--username', required=True)
    p_reset.add_argument('--password', default=None, help='Omit to enter interactively')
    p_reset.set_defaults(func=reset_password)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == '__main__':
    main()
