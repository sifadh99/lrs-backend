"""Members-only reading, roles (user/admin) and blocked accounts."""
import pytest

from app.admin import main as admin_cli
from tests.conftest import STRONG


@pytest.mark.parametrize("path", ["/categories", "/resources", "/resources/1"])
def test_reading_needs_a_login(client, path):
    r = client.get(path)
    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"] == "Bearer"


def test_health_stays_public(client):
    # probes (Docker, Kubernetes) have no token
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 200


def test_new_accounts_are_plain_users(client, reader):
    assert client.get("/auth/me", headers=reader).json()["role"] == "user"


def test_register_cannot_make_an_admin(client):
    # extra fields are ignored: the role is never taken from the request
    body = {"email": "sneaky@x.com", "name": "Sneaky", "password": STRONG, "role": "admin"}
    assert client.post("/auth/register", json=body).json()["role"] == "user"


def test_cli_promote_and_demote(client, admin):
    assert client.get("/auth/me", headers=admin).json()["role"] == "admin"
    assert admin_cli(["demote", "boss@x.com"]) == 0
    # the role is read from the DB on every request: no need to log in again
    assert client.get("/auth/me", headers=admin).json()["role"] == "user"
    assert admin_cli(["promote", "nobody@x.com"]) == 1          # unknown e-mail


def test_blocked_user_is_locked_out_at_once(client, reader):
    assert admin_cli(["block", "reader@x.com"]) == 0
    # the old token stops working on the next request ...
    r = client.get("/resources", headers=reader)
    assert r.status_code == 403 and r.json()["detail"] == "this account is blocked"
    # ... and a new login is refused
    login = client.post("/auth/login", json={"email": "reader@x.com", "password": STRONG})
    assert login.status_code == 403
    # a wrong password still says only "wrong e-mail or password" (no hint it is blocked)
    wrong = client.post("/auth/login", json={"email": "reader@x.com", "password": "Wrong-pass-99"})
    assert wrong.status_code == 401

    assert admin_cli(["unblock", "reader@x.com"]) == 0
    assert client.get("/resources", headers=reader).status_code == 200


def test_cli_set_password(client, reader, monkeypatch):
    import app.admin as cli
    # getpass asks twice (password + confirmation); feed it answers instead of a keyboard
    answers = iter(["short1", "short1", "N3w-strong-pass", "N3w-strong-pass"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": next(answers))

    assert cli.main(["set-password", "reader@x.com"]) == 1          # too weak: refused
    assert cli.main(["set-password", "reader@x.com"]) == 0
    login = {"email": "reader@x.com", "password": "N3w-strong-pass"}
    assert client.post("/auth/login", json=login).status_code == 200
    assert client.post("/auth/login", json={**login, "password": STRONG}).status_code == 401
