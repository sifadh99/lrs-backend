"""Request / response shapes. Pydantic validates every request against these
before our code runs, and FastAPI uses them to build the /docs page."""
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator


# ---------- users / auth ----------
class UserCreate(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=8)

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be blank")
        return v

    @field_validator("password")
    @classmethod
    def bcrypt_limit(cls, v: str) -> str:
        # bcrypt only uses the first 72 BYTES (not characters; "অ" is 3 bytes in UTF-8).
        # bcrypt 5 raises an error above that, so reject it here with a clear message.
        if len(v.encode("utf-8")) > 72:
            raise ValueError("password is too long (max 72 bytes)")
        return v


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):          # what we send back: never the password hash
    id: int
    email: EmailStr
    name: str
    created_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"      # noqa: S105 - the token *type* name, not a secret
    expires_in: int                 # seconds
