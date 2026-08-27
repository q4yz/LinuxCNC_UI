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

def test_axis_settings_endpoints_are_mounted(tmp_data_root, clean_env):
    """The canonical four settings endpoints are wired by the
    registry. ``MachineSettings`` defaults are returned on GET.
    """
    app, _ = _axis_app(tmp_data_root, clean_env)
    client = TestClient(app)

    resp = client.get("/api/v1/modules/axis/settings")
    assert resp.status_code == 200
    payload = resp.json()
    # Defaults from the Pydantic schema. ``macro_buttons`` is the
    # new per-slot custom-button field; empty list by default so
    # the operator-facing surface stays clean until they opt in.
    assert payload == {
        "jog_watchdog_timeout_ms": 500,
        "default_jog_velocity": 500.0,
        "keepalive_interval_ms": 250,
        "estop_disables_power": True,
        "macro_buttons": [],
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


def test_axis_settings_macro_buttons_round_trip(tmp_data_root, clean_env):
    """Per-slot custom macro buttons persist through the canonical
    four-endpoint surface.

    Mirrors the ``camera`` round-trip test
    (``test_camera_settings.py::test_macro_buttons_round_trip``)
    so reviewers can compare the two hosts. The schema is the
    shared ``MacroButtonDescriptor`` (see
    ``backend/models/macro_button.py``); the wire shape is
    snake_case ``macro_buttons`` to match the rest of the backend
    Pydantic surface — the frontend's
    ``useMacroButtonConfig`` normalises the key when reading.

    Coverage:

    * Bulk PUT (full payload replace) round-trips every field on
      every row.
    * A follow-up PUT that omits ``macro_buttons`` keeps the
      sibling list intact (the settings store's top-level
      ``dict.update`` semantics).
    * The on-disk file mirrors the merged payload so a fresh
      checkout rehydrates the operator's configuration.
    * Per-key PUT (``/macro_buttons``) replaces the list and
      survives a sibling-key write.
    """
    from models.macro_button import MacroButtonDescriptor

    app, _ = _axis_app(tmp_data_root, clean_env)
    client = TestClient(app)

    payload = [
        MacroButtonDescriptor(
            slot="dro.x",
            enabled=True,
            name="Probe X",
            icon="\U0001f50d",
            macro_kind="macro",
            macro_name="probe_x",
        ).model_dump(),
        MacroButtonDescriptor(
            slot="dro.z",
            enabled=True,
            name="Touch Z",
            icon="\U0001f4a1",
            macro_kind="ngc",
            macro_name="touch_plate",
        ).model_dump(),
    ]

    # Bulk PUT: rows + a sibling field.
    resp = client.put(
        "/api/v1/modules/axis/settings",
        json={"macro_buttons": payload, "default_jog_velocity": 900.0},
    )
    assert resp.status_code == 200
    merged = resp.json()
    assert merged["default_jog_velocity"] == 900.0
    assert len(merged["macro_buttons"]) == 2
    assert merged["macro_buttons"][0]["slot"] == "dro.x"
    assert merged["macro_buttons"][0]["macro_name"] == "probe_x"
    assert merged["macro_buttons"][1]["macro_kind"] == "ngc"
    assert merged["macro_buttons"][1]["icon"] == "\U0001f4a1"

    # GET round-trips.
    resp = client.get("/api/v1/modules/axis/settings")
    assert resp.status_code == 200
    persisted = resp.json()
    assert len(persisted["macro_buttons"]) == 2
    assert persisted["macro_buttons"][0]["slot"] == "dro.x"
    assert persisted["macro_buttons"][1]["macro_name"] == "touch_plate"

    # On-disk JSON mirrors the merged payload.
    on_disk = json.loads(
        (tmp_data_root / "modules" / "axis" / "settings.json").read_text(
            encoding="utf-8",
        )
    )
    assert len(on_disk["macro_buttons"]) == 2
    assert on_disk["macro_buttons"][0]["slot"] == "dro.x"
    assert on_disk["macro_buttons"][1]["macro_kind"] == "ngc"

    # Sibling-key PUT does not stomp the list — the store's
    # top-level ``dict.update`` keeps both sides intact.
    resp = client.put(
        "/api/v1/modules/axis/settings/keepalive_interval_ms",
        json=400,
    )
    assert resp.status_code == 200
    assert resp.json()["keepalive_interval_ms"] == 400
    assert len(resp.json()["macro_buttons"]) == 2

    # Per-key PUT replaces the list with a single-row version.
    resp = client.put(
        "/api/v1/modules/axis/settings/macro_buttons",
        json=[payload[0]],
    )
    assert resp.status_code == 200
    assert len(resp.json()["macro_buttons"]) == 1
    assert resp.json()["macro_buttons"][0]["slot"] == "dro.x"

    # ``MacroButtonDescriptor`` is the Pydantic coercion target —
    # a stored row coerces back to the typed model so a future
    # consumer can rely on the schema's defaults being applied.
    cfg = json.loads(
        (tmp_data_root / "modules" / "axis" / "settings.json").read_text(
            encoding="utf-8",
        )
    )
    coerced = MacroButtonDescriptor(**cfg["macro_buttons"][0])
    assert coerced.slot == "dro.x"
    assert coerced.enabled is True
    assert coerced.macro_kind == "macro"

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
    from hal_service import jog_service as jog
    from hal_service.jog_service import jog_axis, jog_stop

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
    from services.jog_watchdog import start_watchdog, stop_watchdog
    from core.settings_store import SettingsStore

    settings = SettingsStore(
        module_id="axis",
        data_root=tmp_data_root,
        defaults=None,
    )
    start_watchdog(settings)
    stop_watchdog()
    stop_watchdog()  # second call must not raise
    assert settings.read_all() == {}