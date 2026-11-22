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
    jwt_secret: str = Field(min_length=16)
    jwt_expire_minutes: int = 60
    cors_origins: list[str] = ["http://localhost:5173"]
    db_pool_min: int = 1
    db_pool_max: int = 10


@lru_cache
def get_settings() -> Settings:
    """Read the settings once and reuse them."""
    return Settings()
