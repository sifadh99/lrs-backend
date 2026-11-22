"""Test setup: a separate database (lrs_test), migrated once, emptied before every test.

The env vars are set BEFORE importing the app, because the app reads its settings
(and creates the DB pool) at import time.
"""
import os
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest

STRONG = "Str0ng-pass-42"     # meets the password policy

TEST_DB_URL = os.environ.get("LRS_TEST_DATABASE_URL", "postgresql://lrs:lrs@localhost:5432/lrs_test")
os.environ["LRS_DATABASE_URL"] = TEST_DB_URL
os.environ.setdefault("LRS_JWT_SECRET", "test-secret-that-is-at-least-32-bytes-long")
# Redis logical DB 15: tests never touch the dev cache in DB 0
os.environ.setdefault("LRS_REDIS_URL", "redis://localhost:6379/15")


def _create_test_database() -> None:
    """CREATE DATABASE lrs_test if it does not exist (connect to the default 'postgres' db)."""
    parts = urlsplit(TEST_DB_URL)
    db_name = parts.path.lstrip("/")
    admin_url = urlunsplit(parts._replace(path="/postgres"))
    with psycopg.connect(admin_url, autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,)).fetchone()
        if not exists:
            conn.execute(psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(db_name)))


_create_test_database()

from fastapi.testclient import TestClient  # noqa: E402  (must come after the env setup)

from app import cache  # noqa: E402
from app.main import app  # noqa: E402
from app.migrate import migrate  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _schema():
    migrate()


@pytest.fixture(autouse=True)
def _clean_tables():
    with psycopg.connect(TEST_DB_URL, autocommit=True) as conn:
        conn.execute(
            "TRUNCATE users, resources, resource_details, login_attempts, categories"
            " RESTART IDENTITY CASCADE"
        )
    cache.invalidate()     # the tables are empty again, so no cached answer may survive


@pytest.fixture(scope="session")
def client():
    # "with" runs the lifespan (pool.open ... pool.close) ONCE for the whole test run,
    # just like a real server process. A closed psycopg pool cannot be reopened.
    with TestClient(app) as c:
        yield c


@pytest.fixture
def make_user(client):
    """Create a user and return the headers to call the API as that user."""
    def _make(email: str, name: str = "Tester", password: str = STRONG) -> dict:
        r = client.post("/auth/register", json={"email": email, "name": name, "password": password})
        assert r.status_code == 201, r.text
        token = client.post("/auth/login", json={"email": email, "password": password}).json()["access_token"]
        return {"Authorization": f"Bearer {token}"}
    return _make


@pytest.fixture
def reader(make_user):
    """Headers of an ordinary logged-in member: the site is members-only, even for reading."""
    return make_user("reader@x.com", "Reader")


@pytest.fixture
def admin(make_user):
    """Headers of an admin. Made the only allowed way: the server-side CLI."""
    from app.admin import main as admin_cli
    headers = make_user("boss@x.com", "Boss")
    assert admin_cli(["promote", "boss@x.com"]) == 0
    return headers
