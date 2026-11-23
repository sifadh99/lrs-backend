"""Admin API: dashboard numbers, users (role/block/delete), login security, audit log.

Every route needs an admin (router-level dependency): 401 without login, 403 for
normal users. Every change is written to admin_audit in the same transaction.
"""
import ipaddress
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from psycopg import Connection

from app import audit, cache
from app.db import Conn
from app.routers.auth import MAX_FAILS_PER_EMAIL, MAX_FAILS_PER_IP, WINDOW
from app.schemas import AdminStats, AdminUserOut, AdminUserPatch, AuditOut, SecurityOut
from app.security import AdminUser, require_admin
from app.seed import CURATOR_EMAIL

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])

_USER_SQL = """
SELECT u.id, u.email, u.name, u.role, u.created_at, u.disabled_at,
       (SELECT count(*) FROM resources r WHERE r.user_id = u.id) AS resource_count
FROM users u
"""


def _target_user(conn: Connection, user_id: int, admin: dict) -> dict:
    """The user an admin wants to change, with the two safety rules applied."""
    row = conn.execute(_USER_SQL + " WHERE u.id = %s FOR UPDATE OF u", (user_id,)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    # Locking yourself out (demote/block/delete) could leave the site with no admin.
    if row["id"] == admin["id"]:
        raise HTTPException(status.HTTP_409_CONFLICT, "you cannot change or delete your own account here")
    # The curator owns the curated catalog; deleting it would delete all of it.
    if row["email"].lower() == CURATOR_EMAIL:
        raise HTTPException(status.HTTP_409_CONFLICT, "the curator account is managed by the seed")
    return row


@router.get("/stats", response_model=AdminStats)
def stats(conn: Conn) -> dict:
    # "today" = since midnight in the database's time zone (UTC in our containers)
    row = conn.execute(
        """
        SELECT (SELECT count(*) FROM users)                                    AS users,
               (SELECT count(*) FROM users WHERE role = 'admin')               AS admins,
               (SELECT count(*) FROM users WHERE disabled_at IS NOT NULL)      AS blocked,
               (SELECT count(*) FROM resources)                                AS resources,
               (SELECT count(*) FROM users
                 WHERE created_at >= date_trunc('day', now()))                 AS users_today,
               (SELECT count(*) FROM resources
                 WHERE created_at >= date_trunc('day', now()))                 AS resources_today,
               (SELECT count(*) FROM login_attempts
                 WHERE NOT succeeded AND at > now() - interval '24 hours')    AS failed_logins_24h
        """
    ).fetchone()
    return {**row, "cache": cache.status()}


@router.get("/users", response_model=list[AdminUserOut])
def list_users(
    conn: Conn,
    q: Annotated[str | None, Query(max_length=100, description="part of e-mail or name")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[dict]:
    # ILIKE with a parameter: '%' || %s || '%' is built by PostgreSQL, the input stays data.
    return conn.execute(
        _USER_SQL + """
        WHERE %(q)s::text IS NULL
           OR u.email ILIKE '%%' || %(q)s || '%%' OR u.name ILIKE '%%' || %(q)s || '%%'
        ORDER BY u.id DESC
        LIMIT %(limit)s OFFSET %(offset)s
        """,
        {"q": q or None, "limit": limit, "offset": offset},
    ).fetchall()


@router.patch("/users/{user_id}", response_model=AdminUserOut)
def change_user(user_id: int, body: AdminUserPatch, admin: AdminUser, conn: Conn) -> dict:
    target = _target_user(conn, user_id, admin)
    if body.role is not None and body.role != target["role"]:
        conn.execute("UPDATE users SET role = %s WHERE id = %s", (body.role, user_id))
        audit.record(conn, admin, f"user.role.{body.role}", f"user:{user_id} {target['email']}")
    if body.blocked is not None and body.blocked != (target["disabled_at"] is not None):
        conn.execute(
            "UPDATE users SET disabled_at = CASE WHEN %s THEN now() END WHERE id = %s",
            (body.blocked, user_id),
        )
        action = "user.block" if body.blocked else "user.unblock"
        audit.record(conn, admin, action, f"user:{user_id} {target['email']}")
    return conn.execute(_USER_SQL + " WHERE u.id = %s", (user_id,)).fetchone()


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: int, admin: AdminUser, conn: Conn) -> Response:
    target = _target_user(conn, user_id, admin)
    conn.execute("DELETE FROM users WHERE id = %s", (user_id,))   # resources go by CASCADE
    audit.record(conn, admin, "user.delete", f"user:{user_id} {target['email']}",
                 resources_deleted=target["resource_count"])
    conn.commit()            # commit first, then the cache (see resources._commit_and_invalidate)
    cache.invalidate()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/security", response_model=SecurityOut)
def security(conn: Conn, limit: Annotated[int, Query(ge=1, le=200)] = 50) -> dict:
    failed = conn.execute(
        "SELECT email, host(ip) AS ip, at FROM login_attempts WHERE NOT succeeded"
        " ORDER BY at DESC LIMIT %s",
        (limit,),
    ).fetchall()
    # Same window and limits as the login lockout itself (imported, not copied).
    window = f"interval '{WINDOW}'"
    locked_emails = conn.execute(
        f"SELECT lower(email) AS v FROM login_attempts WHERE NOT succeeded AND at > now() - {window}"  # noqa: S608
        " GROUP BY lower(email) HAVING count(*) >= %s ORDER BY 1",
        (MAX_FAILS_PER_EMAIL,),
    ).fetchall()
    locked_ips = conn.execute(
        f"SELECT host(ip) AS v FROM login_attempts WHERE NOT succeeded AND ip IS NOT NULL"  # noqa: S608
        f" AND at > now() - {window} GROUP BY ip HAVING count(*) >= %s ORDER BY 1",
        (MAX_FAILS_PER_IP,),
    ).fetchall()
    return {
        "failed": failed,
        "locked_emails": [r["v"] for r in locked_emails],
        "locked_ips": [r["v"] for r in locked_ips],
    }


@router.delete("/lockouts", status_code=status.HTTP_204_NO_CONTENT)
def clear_lockout(
    admin: AdminUser,
    conn: Conn,
    email: Annotated[str | None, Query(max_length=320)] = None,
    ip: Annotated[str | None, Query(max_length=45)] = None,
) -> Response:
    """Forget the failed attempts of one e-mail or one IP, so it can log in again now."""
    if (email is None) == (ip is None):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "give exactly one of email or ip")
    if email is not None:
        conn.execute("DELETE FROM login_attempts WHERE NOT succeeded AND lower(email) = lower(%s)", (email,))
    else:
        try:
            ip = str(ipaddress.ip_address(ip))       # validate here, not via a DB error
        except ValueError as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "not an IP address") from e
        conn.execute("DELETE FROM login_attempts WHERE NOT succeeded AND ip = %s::inet", (ip,))
    audit.record(conn, admin, "lockout.clear", f"email:{email}" if email else f"ip:{ip}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/audit", response_model=list[AuditOut])
def audit_log(conn: Conn, limit: Annotated[int, Query(ge=1, le=200)] = 50) -> list[dict]:
    return conn.execute(
        "SELECT id, admin_email, action, target, details, at FROM admin_audit ORDER BY at DESC, id DESC"
        " LIMIT %s",
        (limit,),
    ).fetchall()
