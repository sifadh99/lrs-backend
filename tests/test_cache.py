"""Redis cache: hit/miss, invalidation after writes, and "fail open" when Redis is down."""
import pytest
import redis

from app import cache

needs_redis = pytest.mark.skipif(cache.status() != "up", reason="Redis is not running")
BODY = {"title": "Docker docs", "kind": "docs", "links": ["https://docs.docker.com"]}


@needs_redis
def test_second_read_is_a_hit(client, reader):
    first = client.get("/categories", headers=reader)
    second = client.get("/categories", headers=reader)
    assert first.headers["X-Cache"] == "MISS"
    assert second.headers["X-Cache"] == "HIT"
    assert first.json() == second.json()


@needs_redis
def test_query_params_are_part_of_the_key(client, reader):
    assert client.get("/resources?limit=5", headers=reader).headers["X-Cache"] == "MISS"
    assert client.get("/resources?limit=6", headers=reader).headers["X-Cache"] == "MISS"   # other key
    assert client.get("/resources?limit=5", headers=reader).headers["X-Cache"] == "HIT"


@needs_redis
def test_every_write_invalidates(client, make_user, reader):
    headers = make_user("a@x.com")
    assert client.get("/resources", headers=reader).json() == []
    assert client.get("/resources", headers=reader).headers["X-Cache"] == "HIT"   # empty list cached

    rid = client.post("/resources", json=BODY, headers=headers).json()["id"]
    after_create = client.get("/resources", headers=reader)
    assert after_create.headers["X-Cache"] == "MISS"
    assert [r["id"] for r in after_create.json()] == [rid]                   # not the stale []

    client.put(f"/resources/{rid}", json={**BODY, "title": "Docker manual"}, headers=headers)
    assert client.get("/resources", headers=reader).json()[0]["title"] == "Docker manual"

    client.delete(f"/resources/{rid}", headers=headers)
    assert client.get("/resources", headers=reader).json() == []


@needs_redis
def test_errors_are_not_cached(client, reader):
    assert client.get("/resources?category=nope", headers=reader).status_code == 404
    again = client.get("/resources?category=nope", headers=reader)
    assert again.status_code == 404 and "X-Cache" not in again.headers


def test_redis_down_fails_open(client, monkeypatch, reader):
    # port 1: nothing listens there, so every Redis call fails at once
    dead = redis.Redis(port=1, socket_connect_timeout=0.2, socket_timeout=0.2)
    monkeypatch.setattr(cache, "_client", dead)
    monkeypatch.setattr(cache, "_down_until", 0.0)      # restored after the test

    r = client.get("/categories", headers=reader)
    assert r.status_code == 200 and r.json() == []
    assert r.headers["X-Cache"] == "BYPASS"
    assert client.get("/readyz").json() == {"status": "ready", "cache": "down"}
