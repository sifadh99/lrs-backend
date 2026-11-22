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

    # The token is valid, but the account may have been deleted or blocked since it was
    # issued. Reading the user on every request makes a block (or a lost admin role)
    # count from the very next request, not only when the token expires.
    user = conn.execute(
        "SELECT id, email, name, role, created_at, disabled_at FROM users WHERE id = %s",
        (user_id,),
    ).fetchone()
    if user is None:
        raise _unauthorized("user no longer exists")
    if user["disabled_at"] is not None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "this account is blocked")
    return user


# Use as a parameter type in protected routes:  def route(user: CurrentUser): ...
CurrentUser = Annotated[dict, Depends(get_current_user)]


def require_admin(user: CurrentUser) -> dict:
    """401 if not logged in (from get_current_user), 403 if logged in but not an admin."""
    if user["role"] != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admins only")
    return user


AdminUser = Annotated[dict, Depends(require_admin)]
