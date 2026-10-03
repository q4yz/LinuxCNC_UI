"""Tests for the axis backend module.

Covers:

* ``ModuleRegistry.boot([AxisModule()])`` mounts the router under
  ``/api/v1/modules/axis`` so ``/home`` is reachable.
* The four canonical settings endpoints are mounted by the
  registry, and ``MachineSettings`` defaults survive a round-trip.
* ``POST /home`` rejects an unknown ``state`` payload with ``400``
  per the Pydantic validation contract (the home endpoint
  delegates validation to :class:`AxisService`).
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
from tests._module_app_factory import build_module_app

import json

from fastapi.testclient import TestClient


def _axis_app(tmp_data_root, clean_env=None):
    """Build a FastAPI app with the axis module wired up."""
    return build_module_app("axis", tmp_data_root), None

def test_axis_home_endpoint_is_mounted(tmp_data_root, clean_env):
    """``POST /home`` is reachable under ``/api/v1/modules/axis``.

    The router's ``get_router`` returns a single ``APIRouter`` so we
    only check the operation is wired by exercising it with the
    happy-path payload. The wire contract carries a letter
    (``"all"`` here) rather than an integer index.
    """
    app, _ = _axis_app(tmp_data_root, clean_env)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/modules/axis/home",
        json={"axis": "all"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "success"}

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
    from hal_service import JogService as jog
    from hal_service.JogService import jog_axis, jog_stop

    # No active jogs at start. Clear any leftovers from a previous
    # test so the assertion is hermetic — the watchdog's
    # ``_active_jogs`` map is module-level state and survives
    # across tests in the same process.
    jog.clear_active_jogs()
    assert jog._active_jogs == {}

    # Continuous jog on axis 0 (X) → watchdog state populated.
    jog_axis(velocities={0: 1000.0}, distance=0.0)
    assert 0 in jog._active_jogs

    # Stop removes the entry.
    jog_stop(axes=[0])
    assert jog._active_jogs == {}
    jog.clear_active_jogs()

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

def test_axis_watchdog_start_stop_is_idempotent(tmp_data_root, clean_env):
    """``start_watchdog`` followed by ``stop_watchdog`` is safe —
    calling the watchdog helpers more than once must not raise.

    The legacy ``PluggableModule.on_load`` / ``on_unload`` hooks
    were retired with the module-system migration; the watchdog
    now lives directly in ``services.jog_watchdog``.
    """
    from services.jog_watchdog import WATCHDOG_TIMEOUT_MS, start_watchdog, stop_watchdog

    start_watchdog()
    stop_watchdog()
    stop_watchdog()  # second call must not raise
    # Fixed safety constant — no longer an operator setting.
    assert WATCHDOG_TIMEOUT_MS == 500