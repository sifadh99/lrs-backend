"""Write one row to admin_audit. Called inside the request's transaction, so the log
entry and the change it describes are committed together, or not at all."""
from psycopg import Connection
from psycopg.types.json import Jsonb


def record(conn: Connection, admin: dict, action: str, target: str, **details) -> None:
    conn.execute(
        "INSERT INTO admin_audit (admin_id, admin_email, action, target, details)"
        " VALUES (%s, %s, %s, %s, %s)",
        (admin["id"], admin["email"], action, target, Jsonb(details)),
    )
