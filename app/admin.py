"""Server-side account administration. Not reachable through the API.

    python -m app.admin list
    python -m app.admin promote  you@example.com     # make admin
    python -m app.admin demote   you@example.com     # back to normal user
    python -m app.admin block    spam@example.com
    python -m app.admin unblock  spam@example.com

Why a CLI for the FIRST admin: whoever can run this already has shell access to the
server (or `docker compose exec` / `kubectl exec`), so it needs no extra password and
cannot be reached from the internet. Later admins can also be made from the admin page.
"""
import argparse
import sys

import psycopg
from psycopg.rows import dict_row

from app.config import get_settings

# action -> (SQL SET clause, message). Fixed strings only; the e-mail is a parameter.
_ACTIONS = {
    "promote": ("role = 'admin'", "is now an admin"),
    "demote": ("role = 'user'", "is now a normal user"),
    "block": ("disabled_at = COALESCE(disabled_at, now())", "is blocked"),
    "unblock": ("disabled_at = NULL", "is active again"),
}


def list_users(conn: psycopg.Connection) -> None:
    rows = conn.execute(
        "SELECT id, email, name, role, disabled_at IS NOT NULL AS blocked FROM users ORDER BY id"
    ).fetchall()
    for r in rows:
        flags = " ".join(f for f, on in (("ADMIN", r["role"] == "admin"), ("BLOCKED", r["blocked"])) if on)
        print(f"{r['id']:>4}  {r['email']:<35} {r['name']:<25} {flags}")


def change(conn: psycopg.Connection, action: str, email: str) -> bool:
    set_clause, message = _ACTIONS[action]
    row = conn.execute(
        f"UPDATE users SET {set_clause} WHERE lower(email) = lower(%s) RETURNING email",  # noqa: S608
        (email,),
    ).fetchone()
    if row is None:
        print(f"no user with e-mail {email!r}", file=sys.stderr)
        return False
    print(f"{row['email']} {message}")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.admin", description="GetCode account admin")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("list", help="show all users")
    for action in _ACTIONS:
        sub.add_parser(action).add_argument("email")
    args = parser.parse_args(argv)

    with psycopg.connect(get_settings().database_url, row_factory=dict_row) as conn:
        if args.action == "list":
            list_users(conn)
            return 0
        return 0 if change(conn, args.action, args.email) else 1


if __name__ == "__main__":
    sys.exit(main())
