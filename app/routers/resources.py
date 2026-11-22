"""Create, read, update and delete shared resources. Raw SQL only."""
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status
from psycopg import Connection

from app.db import Conn
from app.schemas import ResourceIn, ResourceOut
from app.security import CurrentUser

router = APIRouter(prefix="/resources", tags=["resources"])

# One query returns resources WITH their links and owner (no N+1 queries).
# {where} is only ever one of the two fixed strings below, never user input;
# all user values go through %s parameters.
_SELECT = """
SELECT r.id, r.title, r.created_at, r.updated_at,
       json_build_object('id', u.id, 'name', u.name)                           AS owner,
       COALESCE(json_agg(d.link ORDER BY d.id) FILTER (WHERE d.id IS NOT NULL),
                '[]'::json)                                                    AS links
FROM resources r
JOIN users u                 ON u.id = r.user_id
LEFT JOIN resource_details d ON d.resource_id = r.id
{where}
GROUP BY r.id, u.id
ORDER BY r.created_at DESC, r.id DESC
"""
_LIST_SQL = _SELECT.format(where="WHERE r.id IN (SELECT id FROM resources"
                                 " ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s)")
_ONE_SQL = _SELECT.format(where="WHERE r.id = %s")


def _fetch_one(conn: Connection, resource_id: int) -> dict:
    row = conn.execute(_ONE_SQL, (resource_id,)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "resource not found")
    return row


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
    # unnest() turns the Python list (sent as one array) into rows: one round trip.
    conn.execute(
        "INSERT INTO resource_details (resource_id, link) SELECT %s, unnest(%s::text[])",
        (resource_id, links),
    )


@router.get("", response_model=list[ResourceOut])
def list_resources(
    conn: Conn,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[dict]:
    return conn.execute(_LIST_SQL, (limit, offset)).fetchall()


@router.get("/{resource_id}", response_model=ResourceOut)
def get_resource(resource_id: int, conn: Conn) -> dict:
    return _fetch_one(conn, resource_id)


@router.post("", response_model=ResourceOut, status_code=status.HTTP_201_CREATED)
def create_resource(body: ResourceIn, user: CurrentUser, conn: Conn) -> dict:
    # Both INSERTs run in the request's single transaction: all or nothing.
    new_id = conn.execute(
        "INSERT INTO resources (title, user_id) VALUES (%s, %s) RETURNING id",
        (body.title, user["id"]),
    ).fetchone()["id"]
    _insert_links(conn, new_id, body.links)
    return _fetch_one(conn, new_id)


@router.put("/{resource_id}", response_model=ResourceOut)
def update_resource(resource_id: int, body: ResourceIn, user: CurrentUser, conn: Conn) -> dict:
    _lock_owned(conn, resource_id, user["id"])
    conn.execute(
        "UPDATE resources SET title = %s, updated_at = now() WHERE id = %s",
        (body.title, resource_id),
    )
    # PUT replaces the whole resource, so the links are replaced too.
    conn.execute("DELETE FROM resource_details WHERE resource_id = %s", (resource_id,))
    _insert_links(conn, resource_id, body.links)
    return _fetch_one(conn, resource_id)


@router.delete("/{resource_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_resource(resource_id: int, user: CurrentUser, conn: Conn) -> Response:
    _lock_owned(conn, resource_id, user["id"])
    conn.execute("DELETE FROM resources WHERE id = %s", (resource_id,))   # links go by CASCADE
    return Response(status_code=status.HTTP_204_NO_CONTENT)
