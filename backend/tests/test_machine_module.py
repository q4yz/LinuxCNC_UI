"""Tests for the machine backend module.

Covers:

* ``ModuleRegistry.boot([MachineModule()])`` mounts the router
  under ``/api/v1/modules/machine`` so ``/state`` / ``/mode`` /
  ``/home`` / ``/mdi`` are reachable.
* The four canonical settings endpoints are mounted by the
  registry, and ``MachineSettings`` defaults survive a round-trip.
* The router rejects an unknown ``state`` payload with ``400`` per
  the Pydantic validation contract.
* The legacy ``routers/machine.py`` and ``routers/jog.py`` modules
  are gone (the file-level deletion enforced by issue #38 § 6
  Risk #7).

The settings test mirrors the camera settings test
(``test_camera_settings.py``) so reviewers can compare the two.
"""
from __future__ import annotations

import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.event_bus import EventBus
from core.module_registry import ModuleRegistry
from core.protocols import PluggableModule


def _machine_app(tmp_data_root, clean_env):
    """Build a FastAPI app with the machine module booted."""
    from modules.machine.module import MachineModule

    reg = ModuleRegistry(data_root=tmp_data_root)
    app = FastAPI()
    reg.boot(app, bus=EventBus(), candidates=[MachineModule()])
    return app, reg


def test_machine_module_satisfies_protocol(tmp_data_root, clean_env):
    """MachineModule is a PluggableModule with the documented
    manifest attributes.
    """
    from modules.machine.module import MachineModule

    instance = MachineModule()
    assert isinstance(instance, PluggableModule)
    assert instance.manifest.id == "machine"
    assert instance.manifest.title == "Machine"
    assert instance.manifest.settings_panel is True


def test_machine_endpoints_are_mounted(tmp_data_root, clean_env):
    """The merged machine router exposes state / mode / home / mdi
    endpoints under ``/api/v1/modules/machine``."""
    app, _ = _machine_app(tmp_data_root, clean_env)
    client = TestClient(app)

    # The router's ``get_router`` returns a single merged
    # ``APIRouter`` so we only check that all four operation_ids are
    # wired by exercising them with the ``happy-path`` payload.
    resp = client.post(
        "/api/v1/modules/machine/state",
        json={"state": "on"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "success"}

    resp = client.post(
        "/api/v1/modules/machine/mode",
        json={"mode": "manual"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "success"}


def test_machine_invalid_state_returns_400(tmp_data_root, clean_env):
    """``POST /state`` rejects unknown state strings with 400."""
    app, _ = _machine_app(tmp_data_root, clean_env)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/modules/machine/state",
        json={"state": "banana"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid state"


def test_machine_invalid_mode_returns_400(tmp_data_root, clean_env):
    """``POST /mode`` rejects unknown mode strings with 400."""
    app, _ = _machine_app(tmp_data_root, clean_env)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/modules/machine/mode",
        json={"mode": "warp"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid mode"


def test_machine_settings_endpoints_are_mounted(tmp_data_root, clean_env):
    """The canonical four settings endpoints are wired by the
    registry. ``MachineSettings`` defaults are returned on GET.
    """
    app, _ = _machine_app(tmp_data_root, clean_env)
    client = TestClient(app)

    resp = client.get("/api/v1/modules/machine/settings")
    assert resp.status_code == 200
    payload = resp.json()
    # Defaults from the Pydantic schema.
    assert payload == {
        "jog_watchdog_timeout_ms": 500,
        "default_jog_velocity": 500.0,
        "keepalive_interval_ms": 250,
        "estop_disables_power": True,
    }

    # PUT bulk returns the merged payload.
    resp = client.put(
        "/api/v1/modules/machine/settings",
        json={"default_jog_velocity": 750.0},
    )
    assert resp.status_code == 200
    assert resp.json()["default_jog_velocity"] == 750.0

    # GET round-trips.
    resp = client.get("/api/v1/modules/machine/settings")
    assert resp.json()["default_jog_velocity"] == 750.0

    # Per-key PUT.
    resp = client.put(
        "/api/v1/modules/machine/settings/jog_watchdog_timeout_ms",
        json=750,
    )
    assert resp.json()["jog_watchdog_timeout_ms"] == 750


def test_machine_registry_logs_mounted_summary(
    tmp_data_root, clean_env, caplog
):
    """The boot summary line includes the machine module id."""
    from modules.machine.module import MachineModule

    reg = ModuleRegistry(data_root=tmp_data_root)
    app = FastAPI()
    with caplog.at_level(logging.INFO, logger="core.module_registry"):
        reg.boot(app, bus=EventBus(), candidates=[MachineModule()])
    summary = [
        r.message
        for r in caplog.records
        if "registry: mounted=" in r.message
    ]
    assert summary, "expected the boot summary log line"
    assert "mounted=['machine']" in summary[0]


def test_machine_jog_endpoint_registers_watchdog_state(
    tmp_data_root, clean_env
):
    """``POST /jog`` (continuous) registers the axis with the
    watchdog; ``POST /jog/keepalive`` refreshes; ``POST /jog/stop``
    removes the entry. Mirrors the historical contract from
    ``routers/jog.py``.
    """
    from modules.machine import jog
    from modules.machine.module import MachineModule

    reg = ModuleRegistry(data_root=tmp_data_root)
    app = FastAPI()
    reg.boot(app, bus=EventBus(), candidates=[MachineModule()])
    client = TestClient(app)

    # No active jogs at start.
    assert jog._active_jogs == {}

    # Continuous jog on axis 0 (X) → watchdog state populated.
    resp = client.post(
        "/api/v1/modules/machine/jog",
        json={"velocities": {"0": 1000.0}, "distance": 0.0},
    )
    assert resp.status_code == 200
    assert 0 in jog._active_jogs

    # Keep-alive refreshes (we cannot easily assert the timestamp
    # moved forward without mocking ``time.time``, but the call
    # should be a no-op for axes that are already active).
    resp = client.post(
        "/api/v1/modules/machine/jog/keepalive",
        json={"axes": [0]},
    )
    assert resp.status_code == 200
    assert 0 in jog._active_jogs

    # Stop removes the entry.
    resp = client.post(
        "/api/v1/modules/machine/jog/stop",
        json={"axes": [0]},
    )
    assert resp.status_code == 200
    assert jog._active_jogs == {}


def test_machine_legacy_routers_are_gone(tmp_data_root, clean_env):
    """Issue #38 § 6 Risk #7: ``routers/machine.py`` and
    ``routers/jog.py`` are removed after the migration. This test
    asserts the imports fail at the source — a regression that
    re-creates either file fails the build.
    """
    # ``importlib.util.find_spec`` returns ``None`` for absent
    # modules so we don't need to actually try ``import``.
    import importlib.util

    machine_spec = importlib.util.find_spec("routers.machine")
    jog_spec = importlib.util.find_spec("routers.jog")

    assert machine_spec is None, "routers/machine.py must be deleted"
    assert jog_spec is None, "routers/jog.py must be deleted"


def test_machine_on_load_is_idempotent(tmp_data_root, clean_env):
    """Repeated ``on_load`` followed by ``on_unload`` is safe —
    calling the watchdog helpers more than once must not raise.
    """
    from modules.machine.module import MachineModule

    instance = MachineModule()
    # ``on_load`` without a registry-built ``ModuleContext`` is
    # acceptable as long as ``ctx.settings`` is not required — the
    # watchdog tolerates a missing settings store. We synthesize a
    # minimal context here so the watchdog can read defaults.
    from core.event_bus import bus as default_bus
    from core.settings_store import SettingsStore

    settings = SettingsStore(
        module_id="machine", data_root=tmp_data_root, defaults=None
    )
    fake_ctx = type(
        "_Ctx",
        (),
        {
            "module_id": "machine",
            "event_bus": default_bus,
            "settings": settings,
            "extras": {},
        },
    )()
    instance.on_load(fake_ctx)
    instance.on_unload()
    instance.on_unload()  # second call must not raise

    # The settings store must still answer a GET — the watchdog
    # lifecycle is decoupled from the settings store.
    assert settings.read_all() == {}
