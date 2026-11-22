"""All configuration comes from environment variables (12-factor app).

Every setting can be given as an env var with the LRS_ prefix, e.g. LRS_DATABASE_URL.
For local development they can also come from a .env file.
"""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LRS_", env_file=".env", extra="ignore")

    database_url: str = "postgresql://lrs:lrs@localhost:5432/lrs"
    # No default on purpose: the app refuses to start without a secret.
    # >= 32 bytes: the minimum for HS256 (RFC 7518 3.2). Generate with: openssl rand -hex 32
    jwt_secret: str = Field(min_length=32)
    jwt_expire_minutes: int = 60
    cors_origins: list[str] = ["http://localhost:5173"]
    db_pool_min: int = 1
    db_pool_max: int = 10
    # Cache. Empty string = no cache at all (the app works the same, only slower).
    redis_url: str = "redis://localhost:6379/0"
    cache_ttl_seconds: int = 300        # safety net: even a missed invalidation heals in 5 min


@lru_cache
def get_settings() -> Settings:
    """Read the settings once and reuse them."""
    return Settings()
