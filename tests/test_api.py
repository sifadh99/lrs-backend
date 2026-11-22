"""API tests against a real PostgreSQL (lrs_test database)."""

DOCKER = {"title": "Docker for beginners", "links": ["https://docs.docker.com", "https://youtu.be/abc"]}


def test_health(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").status_code == 200


def test_register_login_me(client, make_user):
    headers = make_user("Masum@x.com", "Masum")
    me = client.get("/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["email"] == "Masum@x.com"
    assert "password_hash" not in me.json()


def test_duplicate_email_is_case_insensitive(client, make_user):
    make_user("a@x.com")
    r = client.post("/auth/register", json={"email": "A@X.com", "name": "B", "password": "password123"})
    assert r.status_code == 409


def test_wrong_password(client, make_user):
    make_user("a@x.com")
    r = client.post("/auth/login", json={"email": "a@x.com", "password": "nope-nope"})
    assert r.status_code == 401


def test_create_requires_login(client):
    assert client.post("/resources", json=DOCKER).status_code == 401


def test_create_and_list(client, make_user):
    headers = make_user("masum@x.com", "Masum")
    created = client.post("/resources", json=DOCKER, headers=headers)
    assert created.status_code == 201
    body = created.json()
    assert body["links"] == DOCKER["links"]            # same order as sent
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
    assert updated.json()["links"] == ["https://kubernetes.io"]     # links replaced
    assert updated.json()["updated_at"] is not None

    assert client.delete(f"/resources/{rid}", headers=owner).status_code == 204
    assert client.get(f"/resources/{rid}").status_code == 404


def test_missing_resource(client, make_user):
    headers = make_user("a@x.com")
    assert client.get("/resources/999").status_code == 404
    assert client.put("/resources/999", json=DOCKER, headers=headers).status_code == 404
