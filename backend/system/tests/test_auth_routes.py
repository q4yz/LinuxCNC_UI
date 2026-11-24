"""Accounts and logins over HTTP (#131): setup, login, roles, users."""
from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from core.auth import make_authorize
from core.permissions import SYSTEM_ROUTES
from core.users_db import UserStore, set_user_store
from routers import auth as auth_router


@pytest.fixture
def client(tmp_path):
    set_user_store(UserStore(tmp_path / "users.db"))
    auth_router._failures = auth_router._Failures()
    app = FastAPI(dependencies=[Depends(make_authorize(SYSTEM_ROUTES))])
    app.include_router(auth_router.router)
    yield TestClient(app)
    set_user_store(None)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_setup_login_and_roles(client):
    # no account yet: everyone is the local admin, setup is offered
    me = client.get("/api/v1/auth/me").json()
    assert me["role"] == "admin" and me["accounts_exist"] is False and me["authenticated"] is False

    admin = client.post("/api/v1/auth/setup", json={"username": "boss", "password": "secret1"}).json()
    assert admin["user"]["role"] == "admin"
    # a second setup is refused
    assert client.post("/api/v1/auth/setup", json={"username": "x", "password": "secret1"}).status_code == 400

    # without a login: a viewer, who may not manage users
    me = client.get("/api/v1/auth/me").json()
    assert me["role"] == "viewer" and me["accounts_exist"] is True
    assert me["permissions"]["machine.read"] == "allow" and me["permissions"]["machine.motion"] == "deny"
    assert client.get("/api/v1/users").status_code == 403

    # the admin adds a user, who logs in
    headers = _bearer(admin["token"])
    created = client.post("/api/v1/users", json={"username": "worker", "password": "secret2", "role": "user"},
                          headers=headers)
    assert created.status_code == 201
    login = client.post("/api/v1/auth/login", json={"username": "worker", "password": "secret2"}).json()
    assert client.get("/api/v1/auth/me", headers=_bearer(login["token"])).json()["role"] == "user"
    assert client.get("/api/v1/users", headers=_bearer(login["token"])).status_code == 403

    listed = client.get("/api/v1/users", headers=headers).json()
    assert [u["name"] for u in listed["users"]] == ["boss", "worker"]
    assert listed["roles"] == ["admin", "user", "viewer"]

    # the last admin stays an admin
    assert client.put("/api/v1/users/boss", json={"role": "user"}, headers=headers).status_code == 400
    assert client.delete("/api/v1/users/worker", headers=headers).status_code == 204
    assert client.get("/api/v1/auth/me", headers=_bearer(login["token"])).json()["role"] == "viewer"


def test_wrong_passwords_get_slow(client):
    client.post("/api/v1/auth/setup", json={"username": "boss", "password": "secret1"})
    for _ in range(auth_router.MAX_FAILURES):
        assert client.post("/api/v1/auth/login", json={"username": "boss", "password": "nope"}).status_code == 401
    # even the right password waits now
    assert client.post("/api/v1/auth/login", json={"username": "boss", "password": "secret1"}).status_code == 429


def test_change_password_ends_other_sessions(client):
    first = client.post("/api/v1/auth/setup", json={"username": "boss", "password": "secret1"}).json()["token"]
    second = client.post("/api/v1/auth/login", json={"username": "boss", "password": "secret1"}).json()["token"]
    wrong = client.put("/api/v1/auth/password", json={"current_password": "bad", "new_password": "secret9"},
                       headers=_bearer(first))
    assert wrong.status_code == 400
    changed = client.put("/api/v1/auth/password", json={"current_password": "secret1", "new_password": "secret9"},
                         headers=_bearer(first)).json()
    assert client.get("/api/v1/auth/me", headers=_bearer(second)).json()["role"] == "viewer"
    assert client.get("/api/v1/auth/me", headers=_bearer(changed["token"])).json()["role"] == "admin"
    # a viewer has no account to change
    assert client.put("/api/v1/auth/password", json={"current_password": "a", "new_password": "bbbb"}).status_code == 401
