"""Admin API: access rules, user management, safety rules, security view, audit log."""
import pytest

from tests.conftest import STRONG

BODY = {"title": "Docker docs", "kind": "docs", "links": ["https://docs.docker.com"]}
ADMIN_GETS = ["/admin/stats", "/admin/users", "/admin/security", "/admin/audit"]


def _id_of(client, admin, email):
    return next(u["id"] for u in client.get("/admin/users", headers=admin).json() if u["email"] == email)


@pytest.mark.parametrize("path", ADMIN_GETS)
def test_admin_only(client, reader, path):
    assert client.get(path).status_code == 401                    # not logged in
    assert client.get(path, headers=reader).status_code == 403    # logged in, not admin


@pytest.mark.parametrize("path", ADMIN_GETS)
def test_admin_can_read(client, admin, path):
    assert client.get(path, headers=admin).status_code == 200


def test_stats(client, admin, reader):
    s = client.get("/admin/stats", headers=admin).json()
    assert (s["users"], s["admins"], s["blocked"], s["users_today"]) == (2, 1, 0, 2)


def test_user_list_and_search(client, admin, reader):
    users = client.get("/admin/users", headers=admin).json()
    assert {u["email"] for u in users} == {"boss@x.com", "reader@x.com"}
    found = client.get("/admin/users?q=READ", headers=admin).json()      # case-insensitive
    assert [u["email"] for u in found] == ["reader@x.com"]
    assert "password_hash" not in found[0]


def test_block_promote_and_audit(client, admin, reader):
    uid = _id_of(client, admin, "reader@x.com")
    r = client.patch(f"/admin/users/{uid}", json={"blocked": True}, headers=admin)
    assert r.status_code == 200 and r.json()["disabled_at"] is not None
    assert client.get("/resources", headers=reader).status_code == 403    # out at once

    client.patch(f"/admin/users/{uid}", json={"blocked": False, "role": "admin"}, headers=admin)
    assert client.get("/auth/me", headers=reader).json()["role"] == "admin"

    # newest first; the 2nd PATCH wrote two rows in one transaction (same now()),
    # ordered by id: role first, then unblock
    actions = [a["action"] for a in client.get("/admin/audit", headers=admin).json()]
    assert actions == ["user.unblock", "user.role.admin", "user.block", "cli.promote"]


def test_patch_validation(client, admin, reader):
    uid = _id_of(client, admin, "reader@x.com")
    assert client.patch(f"/admin/users/{uid}", json={}, headers=admin).status_code == 422
    assert client.patch(f"/admin/users/{uid}", json={"rol": "admin"}, headers=admin).status_code == 422
    assert client.patch(f"/admin/users/{uid}", json={"role": "root"}, headers=admin).status_code == 422
    assert client.patch("/admin/users/999999", json={"blocked": True}, headers=admin).status_code == 404


def test_admin_cannot_lock_themselves_out(client, admin):
    me = client.get("/auth/me", headers=admin).json()["id"]
    assert client.patch(f"/admin/users/{me}", json={"role": "user"}, headers=admin).status_code == 409
    assert client.patch(f"/admin/users/{me}", json={"blocked": True}, headers=admin).status_code == 409
    assert client.delete(f"/admin/users/{me}", headers=admin).status_code == 409


def test_delete_user_takes_their_resources(client, admin, reader):
    client.post("/resources", json=BODY, headers=reader)
    uid = _id_of(client, admin, "reader@x.com")
    assert client.delete(f"/admin/users/{uid}", headers=admin).status_code == 204
    assert client.get("/resources", headers=admin).json() == []          # cache invalidated too
    last = client.get("/admin/audit", headers=admin).json()[0]
    assert last["action"] == "user.delete" and last["details"] == {"resources_deleted": 1}


def test_admin_moderates_any_resource(client, admin, reader, make_user):
    rid = client.post("/resources", json=BODY, headers=reader).json()["id"]
    other = make_user("other@x.com")
    assert client.delete(f"/resources/{rid}", headers=other).status_code == 403   # normal user: no
    assert client.put(f"/resources/{rid}", json={**BODY, "title": "Fixed"}, headers=admin).status_code == 200
    assert client.delete(f"/resources/{rid}", headers=admin).status_code == 204
    actions = [a["action"] for a in client.get("/admin/audit", headers=admin).json()[:2]]
    assert actions == ["resource.delete", "resource.update"]


def test_own_resource_is_not_audited(client, admin):
    rid = client.post("/resources", json=BODY, headers=admin).json()["id"]
    client.delete(f"/resources/{rid}", headers=admin)
    assert all(a["action"].startswith("cli.") for a in client.get("/admin/audit", headers=admin).json())


def test_security_view_and_unlock(client, admin, reader):
    wrong = {"email": "reader@x.com", "password": "Wrong-pass-99"}
    for _ in range(5):
        client.post("/auth/login", json=wrong)
    sec = client.get("/admin/security", headers=admin).json()
    assert sec["locked_emails"] == ["reader@x.com"]
    assert len(sec["failed"]) == 5 and sec["failed"][0]["email"] == "reader@x.com"

    ok = {"email": "reader@x.com", "password": STRONG}
    assert client.post("/auth/login", json=ok).status_code == 429             # locked
    assert client.delete("/admin/lockouts?email=reader@x.com", headers=admin).status_code == 204
    assert client.post("/auth/login", json=ok).status_code == 200             # free again

    assert client.delete("/admin/lockouts", headers=admin).status_code == 422
    assert client.delete("/admin/lockouts?ip=not-an-ip", headers=admin).status_code == 422
