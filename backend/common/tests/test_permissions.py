"""Every route has a permission; the check refuses what a role may not do."""
from __future__ import annotations

import functools
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocket, WebSocketDisconnect

from core import auth
from core.permissions import (
    BACKENDS,
    PUBLIC_PATHS,
    ROLES,
    Level,
    Permission,
    level,
    permission_table_markdown,
)

BACKEND = Path(__file__).resolve().parents[2]
DOC = BACKEND.parent / "docs" / "reference" / "permissions.md"


_PROBE = """
import json, sys
from fastapi.routing import APIRoute, APIWebSocketRoute
from main import app
routes = []
for r in app.routes:
    if isinstance(r, APIWebSocketRoute):
        routes.append(["WS", r.path])
    elif isinstance(r, APIRoute):
        routes += [[m, r.path] for m in r.methods if m not in ("HEAD", "OPTIONS")]
json.dump({"routes": routes, "schema": app.openapi()}, open(sys.argv[1], "w"))
"""


@functools.cache
def _probe(name: str) -> dict[str, Any]:
    """A backend's routes and schema, read in its own process: both
    backends have a ``services`` package, so they cannot share one."""
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(BACKEND / name), str(BACKEND / "common")])}
    with tempfile.TemporaryDirectory() as tmp:
        result = Path(tmp) / "probe.json"
        subprocess.run([sys.executable, "-c", _PROBE, str(result)], cwd=BACKEND / name, env=env,
                       capture_output=True, text=True, check=True, timeout=120)
        return json.loads(result.read_text(encoding="utf-8"))


def _routes(name: str) -> set[tuple[str, str]]:
    return {(m, p) for m, p in _probe(name)["routes"] if p not in PUBLIC_PATHS}


@pytest.mark.parametrize("name", ["machine", "system"])
def test_every_route_has_exactly_the_tables_permission(name):
    routes = _routes(name)
    table = set(BACKENDS[name])
    assert routes - table == set(), f"routes without a permission in core/permissions.py: {sorted(routes - table)}"
    assert table - routes == set(), f"permissions for routes that no longer exist: {sorted(table - routes)}"


@pytest.mark.parametrize("name", ["machine", "system"])
def test_the_schema_carries_the_permission(name):
    schema = _probe(name)["schema"]
    # the schema writes ``{filename:path}`` as ``{filename}``
    table = {(m, re.sub(r"\{(\w+):path\}", r"{\1}", p)): perm for (m, p), perm in BACKENDS[name].items()}
    for path, operations in schema["paths"].items():
        for method, operation in operations.items():
            permission = table[(method.upper(), path)]
            assert operation["x-permission"] == permission.value
            assert operation["x-agent"] == level("agent", permission).value


def test_roles_are_complete_and_ordered():
    for role in ROLES.values():
        assert set(role) == set(Permission)
    for p in Permission:
        # nobody below admin has something admin lacks; viewer <= operator
        assert level("admin", p) is Level.ALLOW
        if level("viewer", p) is Level.ALLOW:
            assert level("operator", p) is Level.ALLOW
    assert all(level(r, Permission.MACHINE_ESTOP) is Level.ALLOW for r in ROLES), "E-stop for everyone"


def test_the_agent_never_gets_configuration_or_the_system():
    for p in (Permission.CONFIG_WRITE, Permission.HAL_WRITE, Permission.SYSTEM_UPDATE, Permission.USERS_MANAGE,
              Permission.SESSION_CONTROL, Permission.SETTINGS_WRITE, Permission.MACROS_WRITE):
        assert level("agent", p) is Level.DENY
    for p in (Permission.MACHINE_MOTION, Permission.PROGRAM_RUN, Permission.HEATERS):
        assert level("agent", p) is Level.CONFIRM


def test_the_docs_page_is_up_to_date():
    assert DOC.read_text(encoding="utf-8") == permission_table_markdown(), (
        "docs/reference/permissions.md is stale: regenerate it with "
        "core.permissions.permission_table_markdown()"
    )


# -- enforcement on a small app ---------------------------------------------- #

TABLE = {
    ("GET", "/state"): Permission.MACHINE_READ,
    ("POST", "/mdi"): Permission.MACHINE_MOTION,
    ("POST", "/update"): Permission.SYSTEM_UPDATE,
    ("WS", "/ws"): Permission.MACHINE_READ,
    ("WS", "/ws-hal"): Permission.HAL_WRITE,
}


def _client(role: str, monkeypatch) -> TestClient:
    monkeypatch.setattr(auth, "current_user", lambda connection: auth.User("u", role))
    app = FastAPI(dependencies=[__import__("fastapi").Depends(auth.make_authorize(TABLE))])

    @app.get("/state")
    def state():
        return {"ok": True}

    @app.post("/mdi")
    def mdi():
        return {"ok": True}

    @app.post("/update")
    def update():
        return {"ok": True}

    @app.get("/unlisted")
    def unlisted():
        return {"ok": True}

    async def echo(websocket: WebSocket):
        await websocket.accept()
        await websocket.send_text("hi")
        await websocket.close()

    app.add_api_websocket_route("/ws", echo)
    app.add_api_websocket_route("/ws-hal", echo)
    return TestClient(app)


def test_everyone_is_admin_for_now():
    assert auth.current_user(None) == auth.LOCAL_ADMIN


@pytest.mark.parametrize(
    "role, path, code",
    [
        ("admin", "/update", 200),
        ("admin", "/unlisted", 200),
        ("operator", "/mdi", 200),
        ("operator", "/update", 403),
        ("operator", "/unlisted", 403),  # fail closed
        ("viewer", "/mdi", 403),
        ("agent", "/mdi", 403),  # confirm: refused until the confirmation flow exists
        ("nobody", "/state", 403),
    ],
)
def test_the_role_decides(role, path, code, monkeypatch):
    client = _client(role, monkeypatch)
    response = client.get(path) if path in ("/state", "/unlisted") else client.post(path)
    assert response.status_code == code, response.text
    if role == "agent":
        assert "confirmation" in response.json()["detail"]


def test_the_viewer_can_read(monkeypatch):
    assert _client("viewer", monkeypatch).get("/state").status_code == 200


def test_websockets_are_checked(monkeypatch):
    client = _client("viewer", monkeypatch)
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_text() == "hi"
    with pytest.raises(WebSocketDisconnect) as refused:
        with client.websocket_connect("/ws-hal") as ws:
            ws.receive_text()
    assert refused.value.code == 1008
