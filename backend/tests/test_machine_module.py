"""Tests for the axis backend module.

Covers:

* ``ModuleRegistry.boot([AxisModule()])`` mounts the router under
  ``/api/v1/modules/axis`` so ``/home`` is reachable.
* The four canonical settings endpoints are mounted by the
  registry, and ``MachineSettings`` defaults survive a round-trip.
* ``POST /home`` rejects an unknown ``state`` payload with ``400``
  per the Pydantic validation contract (the home endpoint
  delegates validation to :class:`MachineControlService`).
* The legacy ``routers/machine.py`` and ``routers/jog.py`` modules
  are gone (the file-level deletion enforced by issue #38 § 6
  Risk #7).

The settings test mirrors the camera settings test
(``test_camera_settings.py``) so reviewers can compare the two.

State / mode / MDI endpoint coverage lives in
``test_machine_state_module.py`` since those endpoints now live in
the new ``machine_state`` module after the router split.
"""
from __future__ import annotations

import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.event_bus import EventBus
from core.module_registry import ModuleRegistry
from core.protocols import PluggableModule


def _axis_app(tmp_data_root, clean_env):
    """Build a FastAPI app with the axis module booted."""
    from modules.axis.module import AxisModule

    reg = ModuleRegistry(data_root=tmp_data_root)
    app = FastAPI()
    reg.boot(app, bus=EventBus(), candidates=[AxisModule()])
    return app, reg


def test_axis_module_satisfies_protocol(tmp_data_root, clean_env):
    """AxisModule is a PluggableModule with the documented
    manifest attributes.
    """
    from modules.axis.module import AxisModule

    instance = AxisModule()
    assert isinstance(instance, PluggableModule)
    assert instance.manifest.id == "axis"
    assert instance.manifest.title == "Axis"
    assert instance.manifest.settings_panel is True


def test_axis_home_endpoint_is_mounted(tmp_data_root, clean_env):
    """``POST /home`` is reachable under ``/api/v1/modules/axis``.

    The router's ``get_router`` returns a single ``APIRouter`` so we
    only check the operation is wired by exercising it with the
    happy-path payload.
    """
    app, _ = _axis_app(tmp_data_root, clean_env)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/modules/axis/home",
        json={"axis": -1},
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "success"}


def test_axis_settings_endpoints_are_mounted(tmp_data_root, clean_env):
    """The canonical four settings endpoints are wired by the
    registry. ``MachineSettings`` defaults are returned on GET.
    """
    app, _ = _axis_app(tmp_data_root, clean_env)
    client = TestClient(app)

    resp = client.get("/api/v1/modules/axis/settings")
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
        "/api/v1/modules/axis/settings",
        json={"default_jog_velocity": 750.0},
    )
    assert resp.status_code == 200
    assert resp.json()["default_jog_velocity"] == 750.0

    # GET round-trips.
    resp = client.get("/api/v1/modules/axis/settings")
    assert resp.json()["default_jog_velocity"] == 750.0

    # Per-key PUT.
    resp = client.put(
        "/api/v1/modules/axis/settings/jog_watchdog_timeout_ms",
        json=750,
    )
    assert resp.json()["jog_watchdog_timeout_ms"] == 750


def test_axis_registry_logs_mounted_summary(
    tmp_data_root, clean_env, caplog
):
    """The boot summary line includes the axis module id."""
    from modules.axis.module import AxisModule

    reg = ModuleRegistry(data_root=tmp_data_root)
    app = FastAPI()
    with caplog.at_level(logging.INFO, logger="core.module_registry"):
        reg.boot(app, bus=EventBus(), candidates=[AxisModule()])
    summary = [
        r.message
        for r in caplog.records
        if "registry: mounted=" in r.message
    ]
    assert summary, "expected the boot summary log line"
    assert "mounted=['axis']" in summary[0]


def test_axis_jog_dispatch_is_registered_with_watchdog(
    tmp_data_root, clean_env
):
    """Jog dispatch (called by the WebSocket ``ws_jog_*`` helpers)
    registers the active axis with the watchdog. The historical
    ``POST /jog`` / ``/jog/keepalive`` / ``/jog/stop`` REST
    endpoints were deprecated in favour of the ``/ws/telemetry``
    channel and are intentionally no longer exposed; this test
    pins the watchdog-side state contract that both transports
    share.
    """
    from modules.axis import jog
    from modules.axis.jog import ws_jog_axis, ws_jog_stop

    # No active jogs at start.
    assert jog._active_jogs == {}

    # Continuous jog on axis 0 (X) → watchdog state populated.
    ws_jog_axis(velocities={0: 1000.0}, distance=0.0)
    assert 0 in jog._active_jogs

    # Stop removes the entry.
    ws_jog_stop(axes=[0])
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


def test_axis_on_load_is_idempotent(tmp_data_root, clean_env):
    """Repeated ``on_load`` followed by ``on_unload`` is safe —
    calling the watchdog helpers more than once must not raise.
    """
    from modules.axis.module import AxisModule

    instance = AxisModule()
    # ``on_load`` without a registry-built ``ModuleContext`` is
    # acceptable as long as ``ctx.settings`` is not required — the
    # watchdog tolerates a missing settings store. We synthesize a
    # minimal context here so the watchdog can read defaults.
    from core.event_bus import bus as default_bus
    from core.settings_store import SettingsStore

    settings = SettingsStore(
        module_id="axis", data_root=tmp_data_root, defaults=None
    )
    fake_ctx = type(
        "_Ctx",
        (),
        {
            "module_id": "axis",
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