"""Load the curated catalog (seed/catalog.json) into the database.  Run:  python -m app.seed

Idempotent: categories are upserted by slug and curated resources by (category, title),
so it can run on every deploy. Data that users shared is never touched.
Kept apart from the schema migrations on purpose: migrations change the *structure*,
seeding fills in *content*, and the content changes far more often.
"""
import json
import secrets
from pathlib import Path

import bcrypt
import psycopg
from psycopg.rows import dict_row

from app import cache
from app.config import get_settings
from app.media import thumbnail_for

CATALOG = Path(__file__).resolve().parent.parent / "seed" / "catalog.json"
CURATOR_EMAIL = "curator@getcode.local"
CURATOR_NAME = "GetCode Team"


def _curator_id(conn: psycopg.Connection) -> int:
    row = conn.execute("SELECT id FROM users WHERE lower(email) = lower(%s)", (CURATOR_EMAIL,)).fetchone()
    if row:
        return row["id"]
    # A random password nobody knows: the curator account can own data but never log in.
    unusable = bcrypt.hashpw(secrets.token_urlsafe(48).encode(), bcrypt.gensalt()).decode()
    return conn.execute(
        "INSERT INTO users (email, name, password_hash) VALUES (%s, %s, %s) RETURNING id",
        (CURATOR_EMAIL, CURATOR_NAME, unusable),
    ).fetchone()["id"]


def _upsert_category(conn, slug, name, icon, description, parent_id, order) -> int:
    return conn.execute(
        """
        INSERT INTO categories (slug, name, icon, description, parent_id, sort_order)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (slug) DO UPDATE
           SET name = EXCLUDED.name, icon = EXCLUDED.icon, description = EXCLUDED.description,
               parent_id = EXCLUDED.parent_id, sort_order = EXCLUDED.sort_order
        RETURNING id
        """,
        (slug, name, icon, description, parent_id, order),
    ).fetchone()["id"]


def _upsert_resource(conn, curator: int, category_id: int, res: dict) -> bool:
    """Insert or refresh one curated resource. Returns True if it was new."""
    row = conn.execute(
        "SELECT id FROM resources WHERE user_id = %s AND category_id = %s AND title = %s",
        (curator, category_id, res["title"]),
    ).fetchone()
    if row:
        rid, new = row["id"], False
        conn.execute("UPDATE resources SET kind = %s, description = %s WHERE id = %s",
                     (res["kind"], res.get("description"), rid))
        conn.execute("DELETE FROM resource_details WHERE resource_id = %s", (rid,))
    else:
        rid, new = conn.execute(
            "INSERT INTO resources (title, user_id, category_id, kind, description)"
            " VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (res["title"], curator, category_id, res["kind"], res.get("description")),
        ).fetchone()["id"], True
    for link in res["links"]:
        url = link if isinstance(link, str) else link["url"]
        label = None if isinstance(link, str) else link.get("label")
        conn.execute(
            "INSERT INTO resource_details (resource_id, link, label, thumbnail_url) VALUES (%s, %s, %s, %s)",
            (rid, url, label, thumbnail_for(url)),
        )
    return new


def seed(catalog_path: Path = CATALOG) -> dict:
    data = json.loads(catalog_path.read_text())
    stats = {"categories": 0, "resources": 0, "new_resources": 0}
    with psycopg.connect(get_settings().database_url, row_factory=dict_row) as conn, conn.transaction():
        curator = _curator_id(conn)
        for gi, g in enumerate(data["groups"]):
            gid = _upsert_category(conn, g["slug"], g["name"], g.get("icon"), g.get("description"), None, gi)
            stats["categories"] += 1
            for res in g.get("resources", []):
                stats["new_resources"] += _upsert_resource(conn, curator, gid, res)
                stats["resources"] += 1
            for ti, t in enumerate(g.get("topics", [])):
                tid = _upsert_category(
                    conn, t["slug"], t["name"], t.get("icon"), t.get("description"), gid, ti
                )
                stats["categories"] += 1
                for res in t.get("resources", []):
                    stats["new_resources"] += _upsert_resource(conn, curator, tid, res)
                    stats["resources"] += 1
    # the with-block has committed by now; the API's cached copies are out of date
    cache.invalidate()
    return stats


if __name__ == "__main__":
    print("seeded:", seed())
