"""Redis cache for read-heavy endpoints (cache-aside pattern).

Optional by design ("fail open"): if Redis is missing, slow or down, every function
here quietly does nothing and the routes read PostgreSQL as before. The cache may make
the site faster, never broken.

Invalidation uses a version number instead of deleting keys one by one:
    lrs:content:v = 7                           <- one counter
    lrs:v7:categories, lrs:v7:resources:...     <- every cached answer carries it
A write does INCR on the counter; from then on every lookup builds a v8 key, so all the
v7 answers are simply never read again and Redis drops them when their TTL runs out.
"""
import logging
import time
from collections.abc import Callable

import redis
from fastapi import Response

from app.config import get_settings

log = logging.getLogger(__name__)
_settings = get_settings()

# Short timeouts: a cache that makes a request wait seconds is worse than no cache.
_client = (
    redis.Redis.from_url(_settings.redis_url, socket_connect_timeout=0.2, socket_timeout=0.2)
    if _settings.redis_url else None
)
_VERSION_KEY = "lrs:content:v"
_RETRY_AFTER = 30.0       # after an error, leave Redis alone this many seconds (circuit breaker)
_down_until = 0.0         # time.monotonic() value until which we skip Redis


def _usable() -> bool:
    return _client is not None and time.monotonic() >= _down_until


def _trip(err: Exception) -> None:
    """Remember that Redis failed, so the next requests do not each wait for a timeout."""
    global _down_until
    _down_until = time.monotonic() + _RETRY_AFTER
    log.warning("redis unavailable, cache off for %.0fs: %s", _RETRY_AFTER, err)


def _key(parts: tuple) -> str | None:
    """Current versioned key, e.g. lrs:v7:resources:ccna:video:20:0 (None = no cache now)."""
    if not _usable():
        return None
    try:
        version = int(_client.get(_VERSION_KEY) or 0)
    except redis.RedisError as err:
        _trip(err)
        return None
    return f"lrs:v{version}:" + ":".join(str(p) for p in parts)


def cached_json(parts: tuple, build: Callable[[], bytes]) -> Response:
    """Return the cached JSON for `parts`, or call build() (the database) and cache its result.

    The X-Cache header says what happened: HIT, MISS, or BYPASS (cache not available).
    If build() raises (e.g. 404 unknown category), nothing is cached.
    """
    key = _key(parts)
    if key is not None:
        try:
            body = _client.get(key)
            if body is not None:
                return Response(body, media_type="application/json", headers={"X-Cache": "HIT"})
        except redis.RedisError as err:
            _trip(err)
            key = None

    body = build()
    if key is not None:
        try:
            _client.set(key, body, ex=_settings.cache_ttl_seconds)   # ex = TTL in seconds
        except redis.RedisError as err:
            _trip(err)
    return Response(body, media_type="application/json",
                    headers={"X-Cache": "MISS" if key else "BYPASS"})


def invalidate() -> None:
    """Content changed: make every cached answer stale. Call AFTER the DB commit.

    Tried even while the circuit breaker is open: a missed invalidation means stale data,
    which is worse than one slow call. If it still fails, the TTL is the safety net.
    """
    if _client is None:
        return
    try:
        _client.incr(_VERSION_KEY)
    except redis.RedisError as err:
        _trip(err)


def status() -> str:
    """For /readyz: 'up', 'down' or 'disabled'. Never raises."""
    if _client is None:
        return "disabled"
    try:
        _client.ping()
        return "up"
    except redis.RedisError:
        return "down"
