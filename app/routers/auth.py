"""Register, login (with brute-force protection) and "who am I"."""
import ipaddress

from fastapi import APIRouter, HTTPException, Request, status
from psycopg import Connection, errors

from app.db import Conn
from app.schemas import Token, UserCreate, UserLogin, UserOut
from app.security import (
    DUMMY_HASH,
    CurrentUser,
    create_access_token,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])

WINDOW = "15 minutes"
MAX_FAILS_PER_EMAIL = 5      # one account: 5 wrong passwords -> locked for a while
MAX_FAILS_PER_IP = 20        # one address trying many accounts ("password spraying")


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(body: UserCreate, conn: Conn) -> dict:
    try:
        # %s placeholders: the driver sends values separately from the SQL text,
        # so user input can never change the query (no SQL injection).
        return conn.execute(
            """
            INSERT INTO users (email, name, password_hash)
            VALUES (%s, %s, %s)
            RETURNING id, email, name, created_at
            """,
            (body.email, body.name, hash_password(body.password)),
        ).fetchone()
    except errors.UniqueViolation as e:          # users_email_lower_uq
        raise HTTPException(status.HTTP_409_CONFLICT, "an account with this e-mail already exists") from e


def _too_many_failures(conn: Connection, email: str, ip: str | None) -> bool:
    row = conn.execute(
        f"""
        SELECT count(*) FILTER (WHERE lower(email) = lower(%s))  AS by_email,
               count(*) FILTER (WHERE ip = %s)                  AS by_ip
        FROM login_attempts
        WHERE NOT succeeded AND at > now() - interval '{WINDOW}'
        """,  # noqa: S608 - WINDOW is a constant, all user values are %s parameters
        (email, ip),
    ).fetchone()
    return row["by_email"] >= MAX_FAILS_PER_EMAIL or row["by_ip"] >= MAX_FAILS_PER_IP


def _record(conn: Connection, email: str, ip: str | None, ok: bool) -> None:
    conn.execute(
        "INSERT INTO login_attempts (email, ip, succeeded) VALUES (%s, %s, %s)", (email, ip, ok)
    )
    # Commit now: the request transaction is rolled back when we raise 401/429 below,
    # and the failed attempt must still be counted.
    conn.commit()


def _client_ip(request: Request) -> str | None:
    """The caller's IP, or None if it is not a real address (e.g. 'testclient' in tests).

    Behind a proxy (nginx/Traefik) this is the proxy's IP unless uvicorn is told to trust
    X-Forwarded-For (--proxy-headers --forwarded-allow-ips); we set that up in Day 2/5.
    """
    host = request.client.host if request.client else None
    try:
        return str(ipaddress.ip_address(host)) if host else None
    except ValueError:
        return None


@router.post("/login", response_model=Token)
def login(body: UserLogin, request: Request, conn: Conn) -> dict:
    ip = _client_ip(request)
    if _too_many_failures(conn, body.email, ip):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "too many failed login attempts, try again in 15 minutes",
            headers={"Retry-After": "900"},
        )

    user = conn.execute(
        "SELECT id, password_hash FROM users WHERE lower(email) = lower(%s)", (body.email,)
    ).fetchone()
    # Always run bcrypt once, even for unknown e-mails (same response time),
    # and give the same message for "no such user" and "wrong password".
    ok = verify_password(body.password, user["password_hash"] if user else DUMMY_HASH)
    _record(conn, body.email, ip, bool(user and ok))
    if not (user and ok):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "wrong e-mail or password")

    # housekeeping: old attempts are not needed any more
    conn.execute("DELETE FROM login_attempts WHERE at < now() - interval '1 day'")
    token, expires_in = create_access_token(user["id"])
    return {"access_token": token, "expires_in": expires_in}


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> dict:
    return user
