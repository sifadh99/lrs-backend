"""Request / response shapes. Pydantic validates every request against these
before our code runs, and FastAPI uses them to build the /docs page."""
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

# ---------- users / auth ----------
# A few of the most common passwords (real systems check a big list, e.g. haveibeenpwned).
COMMON_PASSWORDS = {
    "password1", "password12", "password123", "password1234", "1234567890", "12345678910",
    "qwertyuiop", "qwerty1234", "qwerty12345", "iloveyou12", "admin12345", "welcome123",
    "abc1234567", "letmein123", "football12", "monkey1234", "dragon1234", "baseball12",
}


class UserCreate(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=10)

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
        if not any(c.isalpha() for c in v) or not any(c.isdigit() for c in v):
            raise ValueError("password must contain both letters and digits")
        if v.lower() in COMMON_PASSWORDS:
            raise ValueError("this password is too common, choose another one")
        return v

    @model_validator(mode="after")
    def password_not_from_email(self) -> "UserCreate":
        # "masum2024!!" for masum@x.com is easy to guess.
        local = self.email.split("@")[0].lower()
        if len(local) >= 4 and local in self.password.lower():
            raise ValueError("password must not contain your e-mail name")
        return self


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


# ---------- resources ----------
# Same rule as the CHECK constraint in the database: must start with http:// or https://
Link = Annotated[str, Field(pattern=r"(?i)^https?://\S+$", max_length=2048)]


Kind = Literal["video", "docs", "tool", "lab", "course", "article"]
Slug = Annotated[str, Field(pattern=r"^[a-z0-9-]{1,40}$")]


class ResourceIn(BaseModel):
    """Body for creating or replacing a resource."""
    title: str = Field(min_length=1, max_length=200)
    links: list[Link] = Field(min_length=1, max_length=10)
    kind: Kind = "article"
    description: str | None = Field(default=None, max_length=500)
    category: Slug | None = None          # topic or group slug, e.g. "ccna"

    @field_validator("title")
    @classmethod
    def strip_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("title must not be blank")
        return v

    @field_validator("description")
    @classmethod
    def blank_description_is_none(cls, v: str | None) -> str | None:
        return (v or "").strip() or None


class Owner(BaseModel):
    id: int
    name: str


class LinkOut(BaseModel):
    url: str
    label: str | None = None          # e.g. the real YouTube title (curated links)
    thumbnail_url: str | None = None  # set for YouTube videos


class CategoryRef(BaseModel):
    slug: str
    name: str


class ResourceOut(BaseModel):
    id: int
    title: str
    kind: Kind
    description: str | None
    category: CategoryRef | None
    links: list[LinkOut]
    owner: Owner
    created_at: datetime
    updated_at: datetime | None


# ---------- categories ----------
class CategoryTopic(BaseModel):
    slug: str
    name: str
    icon: str | None
    description: str | None
    resource_count: int


class CategoryGroup(CategoryTopic):
    total_count: int                   # the group's own resources + all its topics
    topics: list[CategoryTopic]
