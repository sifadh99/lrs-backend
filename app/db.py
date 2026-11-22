"""PostgreSQL access: one connection pool for the whole app, raw SQL only."""
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import get_settings

_settings = get_settings()

# The pool keeps a few connections open and lends them to requests.
# open=False: it is opened in the app's startup (lifespan), not at import time.
pool = ConnectionPool(
    conninfo=_settings.database_url,
    min_size=_settings.db_pool_min,
    max_size=_settings.db_pool_max,
    kwargs={"row_factory": dict_row},   # rows come back as dicts: {"id": 1, "title": ...}
    open=False,
)


def get_conn() -> Iterator[Connection]:
    """FastAPI dependency: borrow a connection for one request.

    The `with` block commits if the request succeeded and rolls back on an exception,
    then returns the connection to the pool.
    """
    with pool.connection() as conn:
        yield conn


# Use as a parameter type in routes:  def route(conn: Conn): ...
Conn = Annotated[Connection, Depends(get_conn)]
