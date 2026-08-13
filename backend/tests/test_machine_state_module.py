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

import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.event_bus import EventBus
from core.module_registry import ModuleRegistry
from core.protocols import PluggableModule


def _state_app(tmp_data_root, clean_env):
    """Build a FastAPI app with the state module booted."""
    from modules.state.module import StateModule

    reg = ModuleRegistry(data_root=tmp_data_root)
    app = FastAPI()
    reg.boot(app, bus=EventBus(), candidates=[StateModule()])
    return app, reg


def test_state_module_satisfies_protocol(tmp_data_root, clean_env):
    """StateModule is a PluggableModule with the documented
    manifest attributes.
    """
    from modules.state.module import StateModule

    instance = StateModule()
    assert isinstance(instance, PluggableModule)
    assert instance.manifest.id == "machine_state"
    assert instance.manifest.title == "Machine State"
    # State module has no user-tunable settings today.
    assert instance.manifest.settings_panel is False


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


def test_state_module_settings_router_returns_empty(
    tmp_data_root, clean_env
):
    """The state module has no Pydantic settings defaults today.

    ``get_settings_model`` returns ``None`` so the registry still
    mounts the canonical settings router (it's a registry-level
    concern, not a per-module opt-out) but with an empty schema.
    ``GET /api/v1/modules/machine_state/settings`` returns an
    empty dict until the module declares a settings model.
    """
    app, _ = _state_app(tmp_data_root, clean_env)
    client = TestClient(app)

    resp = client.get("/api/v1/modules/machine_state/settings")
    assert resp.status_code == 200
    assert resp.json() == {}


def test_state_registry_logs_mounted_summary(
    tmp_data_root, clean_env, caplog
):
    """The boot summary line includes the machine_state module id."""
    from modules.state.module import StateModule

    reg = ModuleRegistry(data_root=tmp_data_root)
    app = FastAPI()
    with caplog.at_level(logging.INFO, logger="core.module_registry"):
        reg.boot(app, bus=EventBus(), candidates=[StateModule()])
    summary = [
        r.message
        for r in caplog.records
        if "registry: mounted=" in r.message
    ]
    assert summary, "expected the boot summary log line"
    assert "mounted=['machine_state']" in summary[0]


def test_state_module_on_load_and_unload_are_idempotent(
    tmp_data_root, clean_env
):
    """``on_load`` / ``on_unload`` are safe to call more than once.

    The state module has no background work to release so the
    hooks are pure no-ops; this test guards against a future
    refactor that accidentally introduces non-idempotent state.
    """
    from modules.state.module import StateModule

    instance = StateModule()
    fake_ctx = type(
        "_Ctx",
        (),
        {"module_id": "machine_state", "extras": {}},
    )()
    instance.on_load(fake_ctx)
    instance.on_unload()
    instance.on_unload()  # second call must not raise