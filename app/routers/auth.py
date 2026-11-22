"""Register, login and "who am I"."""
from fastapi import APIRouter, HTTPException, status
from psycopg import errors

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


@router.post("/login", response_model=Token)
def login(body: UserLogin, conn: Conn) -> dict:
    user = conn.execute(
        "SELECT id, password_hash FROM users WHERE lower(email) = lower(%s)", (body.email,)
    ).fetchone()
    # Always run bcrypt once, even for unknown e-mails (same response time),
    # and give the same message for "no such user" and "wrong password".
    ok = verify_password(body.password, user["password_hash"] if user else DUMMY_HASH)
    if not (user and ok):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "wrong e-mail or password")
    token, expires_in = create_access_token(user["id"])
    return {"access_token": token, "expires_in": expires_in}


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> dict:
    return user
