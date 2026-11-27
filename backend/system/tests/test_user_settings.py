"""Settings per user: an admin's are the shared set, a user's are their own
on top of it (in the user database), viewers and the agent see the shared
set; machine-wide keys only an admin changes."""
from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from core.agent_token import agent_token
from core.auth import make_authorize
from core.permissions import SYSTEM_ROUTES
from core.UiSettingsStore import UiSettingsStore
from core.users_db import UserStore, set_user_store
from routers import auth as auth_router
from routers import ui_settings
from services.UiSettingsService import UiSettingsService, set_ui_settings_service


@pytest.fixture
def rig(tmp_path):
    store = UserStore(tmp_path / "users.db")
    set_user_store(store)
    shared = UiSettingsStore(tmp_path / "settings.json")
    set_ui_settings_service(UiSettingsService(shared))
    auth_router._failures = auth_router._Failures()
    app = FastAPI(dependencies=[Depends(make_authorize(SYSTEM_ROUTES))])
    app.include_router(auth_router.router)
    app.include_router(ui_settings.router)
    client = TestClient(app)
    admin = client.post("/api/v1/auth/login", json={"username": "remora", "password": "remora"}).json()["token"]
    for name in ("anna", "ben"):
        client.post("/api/v1/users", json={"username": name, "password": "secret1", "role": "user"},
                    headers={"Authorization": f"Bearer {admin}"})

    def token(name):
        return client.post("/api/v1/auth/login", json={"username": name, "password": "secret1"}).json()["token"]

    heads = {"admin": {"Authorization": f"Bearer {admin}"}, "anna": {"Authorization": f"Bearer {token('anna')}"},
             "ben": {"Authorization": f"Bearer {token('ben')}"}, "viewer": {},
             "agent": {"Authorization": f"Bearer {agent_token()}"}}
    yield type("R", (), {"client": client, "h": heads, "store": store, "shared": shared})
    set_user_store(None)
    set_ui_settings_service(None)


def values(rig, who):
    return rig.client.get("/api/v1/settings", headers=rig.h[who]).json()


def test_the_admin_sets_the_shared_set_users_add_their_own(rig):
    c, h = rig.client, rig.h
    assert c.put("/api/v1/settings/probing.diameter", json={"value": 6}, headers=h["admin"]).status_code == 200
    # everyone sees the admin's value
    for who in ("anna", "ben", "viewer", "agent"):
        assert values(rig, who)["values"]["probing.diameter"] == 6
    # anna changes it for herself only: in the user database, not the shared file
    assert c.put("/api/v1/settings/probing.diameter", json={"value": 3}, headers=h["anna"]).json()["value"] == 3
    assert values(rig, "anna")["values"]["probing.diameter"] == 3
    assert values(rig, "anna")["personal"] == ["probing.diameter"]
    assert c.get("/api/v1/settings/probing.diameter", headers=h["anna"]).json()["value"] == 3
    for who in ("ben", "viewer", "agent", "admin"):
        assert values(rig, who)["values"]["probing.diameter"] == 6
    assert rig.shared.read_key("probing.diameter") == 6 and rig.store.settings("anna") == {"probing.diameter": 3}
    # reset: back to the admin's
    assert c.delete("/api/v1/settings/probing.diameter", headers=h["anna"]).status_code == 204
    assert values(rig, "anna")["values"]["probing.diameter"] == 6 and values(rig, "anna")["personal"] == []


def test_viewers_and_the_agent_cannot_write(rig):
    c, h = rig.client, rig.h
    assert c.put("/api/v1/settings/probing.diameter", json={"value": 1}, headers=h["viewer"]).status_code == 403
    assert c.put("/api/v1/settings/probing.diameter", json={"value": 1}, headers=h["agent"]).status_code == 403


def test_machine_wide_keys_are_the_admin_s(rig):
    c, h = rig.client, rig.h
    for key in ("camera.ip_camera_url", "slicer.allow_start", "assistant.allow_actions"):
        assert c.put(f"/api/v1/settings/{key}", json={"value": "x"}, headers=h["anna"]).status_code == 403
        assert c.put(f"/api/v1/settings/{key}", json={"value": "x"}, headers=h["admin"]).status_code == 200
    assert "slicer." in values(rig, "anna")["machine_keys"]


def test_a_deleted_user_s_settings_go_with_them(rig):
    rig.client.put("/api/v1/settings/probing.diameter", json={"value": 3}, headers=rig.h["anna"])
    assert rig.client.delete("/api/v1/users/anna", headers=rig.h["admin"]).status_code == 204
    assert rig.store.settings("anna") == {}
