"""API tests against a real PostgreSQL (lrs_test database)."""
import pytest

from tests.conftest import STRONG

DOCKER = {"title": "Docker for beginners", "links": ["https://docs.docker.com", "https://youtu.be/abc"]}


def test_health(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").status_code == 200


def test_readyz_is_503_when_the_pool_has_no_connection(client, monkeypatch):
    # what happens when PostgreSQL is down and the pool cannot open a connection
    from psycopg_pool import PoolTimeout

    from app import main

    def no_connection(*args, **kwargs):
        raise PoolTimeout("couldn't get a connection")

    monkeypatch.setattr(main.pool, "connection", no_connection)
    r = client.get("/readyz")
    assert r.status_code == 503 and r.json() == {"status": "database unavailable"}
    assert client.get("/healthz").status_code == 200        # liveness does not care


def test_register_login_me(client, make_user):
    headers = make_user("Masum@x.com", "Masum")
    me = client.get("/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["email"] == "Masum@x.com"
    assert "password_hash" not in me.json()


def test_duplicate_email_is_case_insensitive(client, make_user):
    make_user("a@x.com")
    r = client.post("/auth/register", json={"email": "A@X.com", "name": "B", "password": STRONG})
    assert r.status_code == 409


def test_wrong_password(client, make_user):
    make_user("a@x.com")
    r = client.post("/auth/login", json={"email": "a@x.com", "password": "nope-nope"})
    assert r.status_code == 401


def test_login_without_account_is_rejected(client):
    r = client.post("/auth/login", json={"email": "ghost@x.com", "password": STRONG})
    assert r.status_code == 401
    assert r.json()["detail"] == "wrong e-mail or password"    # same message as a wrong password


@pytest.mark.parametrize("password", [
    "Short1",              # < 10 characters
    "onlyletterss",        # no digit
    "1234567890",          # no letter (and common)
    "Password123",         # common password (case-insensitive)
    "masum-2024-x",        # contains the e-mail name "masum"
])
def test_weak_passwords_are_rejected(client, password):
    r = client.post("/auth/register", json={"email": "masum@x.com", "name": "M", "password": password})
    assert r.status_code == 422, password


def test_brute_force_lockout(client, make_user):
    make_user("victim@x.com")
    for _ in range(5):
        bad = client.post("/auth/login", json={"email": "victim@x.com", "password": "guess-12345"})
        assert bad.status_code == 401
    # 6th try is blocked even with the RIGHT password: the attacker cannot tell when they guessed it
    locked = client.post("/auth/login", json={"email": "victim@x.com", "password": STRONG})
    assert locked.status_code == 429
    assert locked.headers["Retry-After"] == "900"
    # other accounts are not affected
    make_user("someone@x.com")


def test_create_requires_login(client):
    assert client.post("/resources", json=DOCKER).status_code == 401


def test_create_and_list(client, make_user):
    headers = make_user("masum@x.com", "Masum")
    created = client.post("/resources", json=DOCKER, headers=headers)
    assert created.status_code == 201
    body = created.json()
    assert [link["url"] for link in body["links"]] == DOCKER["links"]   # same order as sent
    assert body["kind"] == "article" and body["category"] is None       # defaults
    assert body["owner"]["name"] == "Masum"
    assert body["updated_at"] is None

    listed = client.get("/resources").json()            # public, no token needed
    assert [r["id"] for r in listed] == [body["id"]]


def test_list_is_newest_first_and_paginated(client, make_user):
    headers = make_user("a@x.com")
    ids = [client.post("/resources", json={**DOCKER, "title": f"R{i}"}, headers=headers).json()["id"]
           for i in range(3)]
    assert [r["id"] for r in client.get("/resources").json()] == ids[::-1]
    assert [r["id"] for r in client.get("/resources?limit=2&offset=1").json()] == ids[::-1][1:3]


def test_validation(client, make_user):
    headers = make_user("a@x.com")
    bad = [
        {"title": "   ", "links": ["https://ok.com"]},          # blank title
        {"title": "x", "links": []},                             # no links
        {"title": "x", "links": ["ftp://old.site"]},             # not http(s)
        {"title": "x" * 201, "links": ["https://ok.com"]},       # too long
    ]
    for body in bad:
        assert client.post("/resources", json=body, headers=headers).status_code == 422, body


def test_only_owner_can_update_or_delete(client, make_user):
    owner = make_user("owner@x.com")
    other = make_user("other@x.com")
    rid = client.post("/resources", json=DOCKER, headers=owner).json()["id"]
    new = {"title": "Changed", "links": ["https://kubernetes.io"]}

    assert client.put(f"/resources/{rid}", json=new, headers=other).status_code == 403
    assert client.delete(f"/resources/{rid}", headers=other).status_code == 403

    updated = client.put(f"/resources/{rid}", json=new, headers=owner)
    assert updated.status_code == 200
    assert [link["url"] for link in updated.json()["links"]] == ["https://kubernetes.io"]  # replaced
    assert updated.json()["updated_at"] is not None

    assert client.delete(f"/resources/{rid}", headers=owner).status_code == 204
    assert client.get(f"/resources/{rid}").status_code == 404


def test_missing_resource(client, make_user):
    headers = make_user("a@x.com")
    assert client.get("/resources/999").status_code == 404
    assert client.put("/resources/999", json=DOCKER, headers=headers).status_code == 404
