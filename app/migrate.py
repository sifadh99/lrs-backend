"""Tiny migration runner: applies migrations/NNN_name.sql files that were not applied yet.

Run it with:  python -m app.migrate
"""
from pathlib import Path

import psycopg

from app.config import get_settings

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
LOCK_ID = 4242  # any fixed number; all app instances use the same one


def migrate() -> list[str]:
    applied_now: list[str] = []
    with psycopg.connect(get_settings().database_url, autocommit=True) as conn:
        # If several copies of the app start at once (Kubernetes replicas), only one
        # may run migrations. The others wait here until the first one is finished.
        conn.execute("SELECT pg_advisory_lock(%s)", (LOCK_ID,))
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                " version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
            done = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}

            for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
                version = path.stem                      # "001_init"
                if version in done:
                    continue
                # One transaction per file: the SQL and the bookkeeping row succeed together
                # or not at all.
                with conn.transaction():
                    conn.execute(path.read_text())
                    conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
                applied_now.append(version)
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_ID,))
    return applied_now


if __name__ == "__main__":
    applied = migrate()
    print("applied:", ", ".join(applied) if applied else "nothing (database is up to date)")
