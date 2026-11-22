"""Password hashing (bcrypt) and login tokens (JWT)."""
from datetime import UTC, datetime, timedelta
from typing import Annotated

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings
from app.db import Conn

ALGORITHM = "HS256"
_settings = get_settings()
_bearer = HTTPBearer(auto_error=False)    # reads "Authorization: Bearer <token>"


# ---------- passwords ----------
def hash_password(password: str) -> str:
    # gensalt() = random salt per password; cost 12 = 2^12 rounds, deliberately slow.
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


# Used when the e-mail does not exist, so a failed login takes the same time
# whether or not the account exists (otherwise attackers can find valid e-mails).
DUMMY_HASH = hash_password("not-a-real-password")


# ---------- tokens ----------
def create_access_token(user_id: int) -> tuple[str, int]:
    now = datetime.now(UTC)
    expires = timedelta(minutes=_settings.jwt_expire_minutes)
    payload = {"sub": str(user_id), "iat": now, "exp": now + expires}
    return jwt.encode(payload, _settings.jwt_secret, algorithm=ALGORITHM), int(expires.total_seconds())


def _unauthorized(detail: str = "not authenticated") -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"})


BearerCreds = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]


def get_current_user(creds: BearerCreds, conn: Conn) -> dict:
    """Dependency for protected routes: returns the logged-in user or answers 401."""
    if creds is None:
        raise _unauthorized()
    try:
        # algorithms=[...] is required: never let the token choose its own algorithm.
        payload = jwt.decode(creds.credentials, _settings.jwt_secret, algorithms=[ALGORITHM])
        user_id = int(payload["sub"])
    except jwt.ExpiredSignatureError as e:
        raise _unauthorized("token expired") from e
    except (jwt.InvalidTokenError, KeyError, ValueError) as e:
        raise _unauthorized("invalid token") from e

    # The token is valid, but the account may have been deleted since it was issued.
    user = conn.execute(
        "SELECT id, email, name, created_at FROM users WHERE id = %s", (user_id,)
    ).fetchone()
    if user is None:
        raise _unauthorized("user no longer exists")
    return user


# Use as a parameter type in protected routes:  def route(user: CurrentUser): ...
CurrentUser = Annotated[dict, Depends(get_current_user)]
