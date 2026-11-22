"""Create, read, update and delete shared resources. Raw SQL only."""
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status
from psycopg import Connection
from pydantic import TypeAdapter

from app import cache
from app.db import Conn
from app.media import thumbnail_for
from app.schemas import Kind, ResourceIn, ResourceOut, Slug
from app.security import CurrentUser

router = APIRouter(prefix="/resources", tags=["resources"])

# One query returns resources WITH their links, owner and category (no N+1 queries).
# {where} is only ever one of the fixed strings below, never user input;
# all user values go through %s parameters.
_SELECT = """
SELECT r.id, r.title, r.kind, r.description, r.created_at, r.updated_at,
       json_build_object('id', u.id, 'name', u.name)                              AS owner,
       CASE WHEN c.id IS NULL THEN NULL
            ELSE json_build_object('slug', c.slug, 'name', c.name) END            AS category,
       COALESCE(json_agg(json_build_object('url', d.link, 'label', d.label,
                                           'thumbnail_url', d.thumbnail_url)
                         ORDER BY d.id) FILTER (WHERE d.id IS NOT NULL), '[]'::json) AS links
FROM resources r
JOIN users u                 ON u.id = r.user_id
LEFT JOIN categories c       ON c.id = r.category_id
LEFT JOIN resource_details d ON d.resource_id = r.id
{where}
GROUP BY r.id, u.id, c.id
ORDER BY r.created_at DESC, r.id DESC
"""
# Pick the page of resource IDs first, then join (LIMIT on joined rows would cut links).
_LIST_SQL = _SELECT.format(where="""
WHERE r.id IN (
    SELECT id FROM resources
    WHERE (%(category_id)s::bigint IS NULL OR category_id = %(category_id)s)
      AND (%(kind)s::text IS NULL OR kind = %(kind)s)
    ORDER BY created_at DESC, id DESC
    LIMIT %(limit)s OFFSET %(offset)s)""")
_ONE_SQL = _SELECT.format(where="WHERE r.id = %(id)s")
_LIST = TypeAdapter(list[ResourceOut])      # validates + serializes a list to JSON bytes


def _commit_and_invalidate(conn: Connection) -> None:
    """Commit FIRST, then make the cache stale.

    The other way round, a reader could slip in between, read the old (not yet committed)
    rows from PostgreSQL and put them back into the cache under the new version.
    get_conn() would commit anyway when the request ends; committing earlier is harmless.
    """
    conn.commit()
    cache.invalidate()


def _fetch_one(conn: Connection, resource_id: int) -> dict:
    row = conn.execute(_ONE_SQL, {"id": resource_id}).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "resource not found")
    return row


def _category_id(conn: Connection, slug: str | None, error: int) -> int | None:
    if slug is None:
        return None
    row = conn.execute("SELECT id FROM categories WHERE slug = %s", (slug,)).fetchone()
    if row is None:
        raise HTTPException(error, f"unknown category '{slug}'")
    return row["id"]


def _lock_owned(conn: Connection, resource_id: int, user_id: int) -> None:
    """404 if the resource does not exist, 403 if it belongs to someone else.

    FOR UPDATE locks the row until the transaction ends, so two edits of the
    same resource cannot interleave.
    """
    row = conn.execute(
        "SELECT user_id FROM resources WHERE id = %s FOR UPDATE", (resource_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "resource not found")
    if row["user_id"] != user_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "only the owner can change this resource")


def _insert_links(conn: Connection, resource_id: int, links: list[str]) -> None:
    # unnest() of two parallel arrays -> one row per link: one round trip for all links.
    conn.execute(
        """
        INSERT INTO resource_details (resource_id, link, thumbnail_url)
        SELECT %s, l, t FROM unnest(%s::text[], %s::text[]) AS x(l, t)
        """,
        (resource_id, links, [thumbnail_for(u) for u in links]),
    )


@router.get("", response_model=list[ResourceOut])
def list_resources(
    conn: Conn,
    category: Annotated[Slug | None, Query(description="topic or group slug")] = None,
    kind: Kind | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Response:
    def build() -> bytes:
        # the unknown-category 404 is raised in here, so an error is never cached
        params = {
            "category_id": _category_id(conn, category, status.HTTP_404_NOT_FOUND),
            "kind": kind, "limit": limit, "offset": offset,
        }
        return _LIST.dump_json(_LIST.validate_python(conn.execute(_LIST_SQL, params).fetchall()))

    # every query parameter is part of the key: ?category=ccna and ?category=cka differ
    return cache.cached_json(("resources", category or "-", kind or "-", limit, offset), build)


@router.get("/{resource_id}", response_model=ResourceOut)
def get_resource(resource_id: int, conn: Conn) -> dict:
    return _fetch_one(conn, resource_id)


@router.post("", response_model=ResourceOut, status_code=status.HTTP_201_CREATED)
def create_resource(body: ResourceIn, user: CurrentUser, conn: Conn) -> dict:
    category_id = _category_id(conn, body.category, status.HTTP_422_UNPROCESSABLE_CONTENT)
    # Both INSERTs run in the request's single transaction: all or nothing.
    new_id = conn.execute(
        "INSERT INTO resources (title, user_id, category_id, kind, description)"
        " VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (body.title, user["id"], category_id, body.kind, body.description),
    ).fetchone()["id"]
    _insert_links(conn, new_id, body.links)
    created = _fetch_one(conn, new_id)
    _commit_and_invalidate(conn)
    return created


@router.put("/{resource_id}", response_model=ResourceOut)
def update_resource(resource_id: int, body: ResourceIn, user: CurrentUser, conn: Conn) -> dict:
    _lock_owned(conn, resource_id, user["id"])
    category_id = _category_id(conn, body.category, status.HTTP_422_UNPROCESSABLE_CONTENT)
    conn.execute(
        "UPDATE resources SET title = %s, kind = %s, description = %s, category_id = %s,"
        " updated_at = now() WHERE id = %s",
        (body.title, body.kind, body.description, category_id, resource_id),
    )
    # PUT replaces the whole resource, so the links are replaced too.
    conn.execute("DELETE FROM resource_details WHERE resource_id = %s", (resource_id,))
    _insert_links(conn, resource_id, body.links)
    updated = _fetch_one(conn, resource_id)
    _commit_and_invalidate(conn)
    return updated


@router.delete("/{resource_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_resource(resource_id: int, user: CurrentUser, conn: Conn) -> Response:
    _lock_owned(conn, resource_id, user["id"])
    conn.execute("DELETE FROM resources WHERE id = %s", (resource_id,))   # links go by CASCADE
    _commit_and_invalidate(conn)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
