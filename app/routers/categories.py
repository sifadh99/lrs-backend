"""The category tree: groups (Network, DevOps, ...) with their topics (CCNA, CKA, ...)."""
from fastapi import APIRouter

from app.db import Conn
from app.schemas import CategoryGroup

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("", response_model=list[CategoryGroup])
def list_categories(conn: Conn) -> list[dict]:
    rows = conn.execute(
        """
        SELECT c.slug, c.name, c.icon, c.description, p.slug AS parent,
               (SELECT count(*) FROM resources r WHERE r.category_id = c.id) AS resource_count
        FROM categories c
        LEFT JOIN categories p ON p.id = c.parent_id
        ORDER BY c.sort_order, c.name
        """
    ).fetchall()
    groups = {r["slug"]: {**r, "topics": []} for r in rows if r["parent"] is None}
    for r in rows:
        if r["parent"] in groups:
            groups[r["parent"]]["topics"].append(r)
    for g in groups.values():   # a group's total includes its topics
        g["total_count"] = g["resource_count"] + sum(t["resource_count"] for t in g["topics"])
    return list(groups.values())
