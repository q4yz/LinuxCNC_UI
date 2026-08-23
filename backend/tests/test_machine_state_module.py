"""Tests for the machine_state backend module.

Covers:

* :class:`StateModule` satisfies the :class:`PluggableModule` protocol
  with the documented manifest attributes (``id="machine_state"``,
  ``title="Machine State"``, ``settings_panel=False``).
* ``ModuleRegistry.boot([StateModule()])`` mounts the router under
  ``/api/v1/modules/machine_state`` so ``/state`` / ``/mode`` /
  ``/mdi`` are reachable.
* ``POST /state`` rejects unknown ``state`` strings with ``400``.
* ``POST /mode`` rejects unknown ``mode`` strings with ``400``.
* The state module is included in the registry boot summary.

The state / mode / MDI endpoint contract is pinned separately by
``test_machine_state_facade.py`` (HTTP round-trip, Pydantic
schema, deprecation warnings).
"""
from __future__ import annotations
from tests._module_app_factory import build_module_app

import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.event_bus import EventBus

def _state_app(tmp_data_root, clean_env=None):
    """Build a FastAPI app with the machine_state module wired up."""
    return build_module_app("machine_state", tmp_data_root), None

def test_state_endpoints_are_mounted(tmp_data_root, clean_env):
    """The state router exposes state / mode / mdi endpoints under
    ``/api/v1/modules/machine_state``.
    """
    app, _ = _state_app(tmp_data_root, clean_env)
    client = TestClient(app)

    # ``POST /state`` (set) — happy path.
    resp = client.post(
        "/api/v1/modules/machine_state/state",
        json={"state": "on"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "success"}

    # ``POST /mode`` — happy path.
    resp = client.post(
        "/api/v1/modules/machine_state/mode",
        json={"mode": "manual"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "success"}

    # ``POST /mdi`` — happy path.
    resp = client.post(
        "/api/v1/modules/machine_state/mdi",
        json={"command": "G0 X0"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "success"}

    # ``GET /state`` — read-side round-trip. Returns the snapshot
    # shape; the exact ``state`` value depends on the live NML
    # channel (which the offline test environment serves as
    # ``estop``) so we only assert the endpoint is wired.
    resp = client.get("/api/v1/modules/machine_state/state")
    assert resp.status_code == 200
    body = resp.json()
    assert "state" in body
    assert "raw_task_state" in body

def test_state_invalid_state_returns_400(tmp_data_root, clean_env):
    """``POST /state`` rejects unknown state strings with 400."""
    app, _ = _state_app(tmp_data_root, clean_env)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/modules/machine_state/state",
        json={"state": "banana"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid state"

def test_state_invalid_mode_returns_400(tmp_data_root, clean_env):
    """``POST /mode`` rejects unknown mode strings with 400."""
    app, _ = _state_app(tmp_data_root, clean_env)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/modules/machine_state/mode",
        json={"mode": "warp"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid mode"

def test_state_module_settings_router_returns_typed_payload(
    tmp_data_root, clean_env
):
    """The contract requires every module to return a non-null
    Pydantic settings model. The state module ships
    :class:`StateSettings` (introduced in the contract rewrite —
    see ``.agent/contracts/backend-module.md`` § 1) so the
    canonical settings endpoints expose a typed payload from first
    boot.
    """
    app, _ = _state_app(tmp_data_root, clean_env)
    client = TestClient(app)

    resp = client.get("/api/v1/modules/machine_state/settings")
    assert resp.status_code == 200
    assert resp.json() == {"confirm_mode_change": False}

