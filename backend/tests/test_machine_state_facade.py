"""Tests for the state-facade read path on ``MachineControlService``.

These tests pin the contract that hides the linuxcnc NML integer
constants from API consumers. Every test runs hermetically: the
NML stat channel is replaced via ``unittest.mock.patch.object`` so
no real LinuxCNC instance is needed.

Coverage:

* ``MachineState`` enum surface — values, JSON serialisability.
* ``MachineControlService.get_state()`` — every priority branch
  (OFFLINE / ESTOP / POWER_OFF / IDLE / LOADED / RUNNING / PAUSED /
  FAILURE).
* ``MachineControlService.get_state_snapshot()`` — JSON shape
  stability, ``raw_*`` field round-trip.
* ``GET /api/v1/modules/machine/state`` — FastAPI round-trip via
  ``TestClient``.
* Deprecation warnings on the legacy ``get_machine_stat`` /
  ``get_machine_cmd`` / ``get_machine_error`` /
  ``is_linuxcnc_connected`` passthroughs.
* No ``STATE_*`` / ``INTERP_*`` integer leaks in the public
  Pydantic schema (``_StateSnapshot``).
"""

from __future__ import annotations

import importlib
import json
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# Resolve the ``hardware.connection`` module without going through
# the package ``__init__`` (which re-exports ``connection = Connection()``,
# the legacy instance — not what we want here).
conn_mod = importlib.import_module("hardware.connection")

# ``linuxcnc`` is the mock fallback in the test environment; its
# constants match the real NML integers 1-4 so the state facade
# maps cleanly.
linuxcnc = conn_mod.linuxcnc

from services.machine_service import (  # noqa: E402
    MachineControlService,
    MachineState,
)
from modules.state.router import router as state_router  # noqa: E402


# ---------------------------------------------------------------------- #
# Helpers                                                                 #
# ---------------------------------------------------------------------- #


def _fake_stat(**attrs):
    """Build a stat-like object with the given attributes.

    Defaults match the offline snapshot so a test that does not
    override a field still has a well-defined value.
    """

    defaults = {
        "task_state": getattr(linuxcnc, "STATE_ESTOP", 1),
        "estop": 1,
        "task_mode": getattr(linuxcnc, "MODE_MANUAL", 1),
        "interp_state": getattr(linuxcnc, "INTERP_IDLE", 1),
        "file": "",
        "homed": [0, 0, 0],
        "position": [0.0] * 9,
        "actual_position": [0.0] * 9,
        "g5x_index": 1,
    }
    defaults.update(attrs)

    class _Stat:
        def __init__(self, store):
            self._store = store

        def __getattr__(self, name):
            return self._store.get(name, 0)

        def poll(self):
            return None

    return _Stat(defaults)


# ---------------------------------------------------------------------- #
# MachineState enum                                                       #
# ---------------------------------------------------------------------- #


class TestMachineStateEnum:
    """The enum is the public contract; pin its values."""

    def test_enum_values_are_lowercase_strings(self):
        """The whole point of the facade is that consumers never
        see NML integer constants. ``.value`` is the wire format.
        """
        assert MachineState.OFFLINE.value == "offline"
        assert MachineState.ESTOP.value == "estop"
        assert MachineState.POWER_OFF.value == "power_off"
        assert MachineState.IDLE.value == "idle"
        assert MachineState.LOADED.value == "loaded"
        assert MachineState.RUNNING.value == "running"
        assert MachineState.PAUSED.value == "paused"
        assert MachineState.FAILURE.value == "failure"

    def test_enum_is_json_serialisable(self):
        """``json.dumps`` on an enum member returns the bare string
        so the API contract is stable without a custom encoder.
        """
        assert json.dumps(MachineState.IDLE) == '"idle"'
        assert json.dumps(MachineState.RUNNING) == '"running"'

    def test_enum_is_str_subclass(self):
        """The ``str`` mixin is what makes JSON serialisation work
        out of the box; a refactor that drops it breaks the wire.
        """
        assert isinstance(MachineState.IDLE, str)


# ---------------------------------------------------------------------- #
# get_state()                                                             #
# ---------------------------------------------------------------------- #


class TestGetState:
    """``get_state`` is the canonical facade method."""

    def test_returns_offline_when_stat_channel_is_none(self):
        """NML channel has not connected yet → ``OFFLINE``."""
        svc = MachineControlService()
        with patch.object(conn_mod, "get_machine_stat", return_value=None):
            assert svc.get_state() is MachineState.OFFLINE

    def test_returns_estop_when_task_state_is_estop(self):
        """``STATE_ESTOP`` → ``ESTOP``."""
        svc = MachineControlService()
        stat = _fake_stat(
            task_state=getattr(linuxcnc, "STATE_ESTOP", 1),
            estop=1,
        )
        with patch.object(conn_mod, "get_machine_stat", return_value=stat):
            assert svc.get_state() is MachineState.ESTOP

    def test_estop_bit_wins_over_task_state(self):
        """The ``estop`` bit wins over ``task_state`` — the
        frontend state facade applies the same priority, so the
        backend cannot disagree.
        """
        svc = MachineControlService()
        stat = _fake_stat(
            task_state=getattr(linuxcnc, "STATE_ON", 4),
            estop=1,
        )
        with patch.object(conn_mod, "get_machine_stat", return_value=stat):
            assert svc.get_state() is MachineState.ESTOP

    @pytest.mark.parametrize("task_state", [
        getattr(linuxcnc, "STATE_OFF", 3),
        getattr(linuxcnc, "STATE_ESTOP_RESET", 2),
    ])
    def test_returns_power_off_when_off_or_estop_reset(self, task_state):
        """``STATE_OFF`` and ``STATE_ESTOP_RESET`` both surface as
        ``POWER_OFF`` — the operator only cares whether the
        machine is ready to take a cut.
        """
        svc = MachineControlService()
        stat = _fake_stat(task_state=task_state, estop=0)
        with patch.object(conn_mod, "get_machine_stat", return_value=stat):
            assert svc.get_state() is MachineState.POWER_OFF

    def test_returns_loaded_when_file_set_and_interp_idle(self):
        """``STATE_ON`` + ``INTERP_IDLE`` + file path → ``LOADED``."""
        svc = MachineControlService()
        stat = _fake_stat(
            task_state=getattr(linuxcnc, "STATE_ON", 4),
            estop=0,
            interp_state=getattr(linuxcnc, "INTERP_IDLE", 1),
            file="/tmp/example.gcode",
        )
        with patch.object(conn_mod, "get_machine_stat", return_value=stat):
            assert svc.get_state() is MachineState.LOADED

    @pytest.mark.parametrize("interp_state", [
        getattr(linuxcnc, "INTERP_READING", 2),
        getattr(linuxcnc, "INTERP_WAITING", 4),
    ])
    def test_returns_running_when_interp_reading_or_waiting(
        self, interp_state
    ):
        """``INTERP_READING`` and ``INTERP_WAITING`` both surface
        as ``RUNNING`` — the operator just needs to know "is the
        cut active?".
        """
        svc = MachineControlService()
        stat = _fake_stat(
            task_state=getattr(linuxcnc, "STATE_ON", 4),
            estop=0,
            interp_state=interp_state,
        )
        with patch.object(conn_mod, "get_machine_stat", return_value=stat):
            assert svc.get_state() is MachineState.RUNNING

    def test_returns_paused_when_interp_paused(self):
        svc = MachineControlService()
        stat = _fake_stat(
            task_state=getattr(linuxcnc, "STATE_ON", 4),
            estop=0,
            interp_state=getattr(linuxcnc, "INTERP_PAUSED", 3),
        )
        with patch.object(conn_mod, "get_machine_stat", return_value=stat):
            assert svc.get_state() is MachineState.PAUSED

    def test_returns_idle_when_no_file_and_interp_idle(self):
        svc = MachineControlService()
        stat = _fake_stat(
            task_state=getattr(linuxcnc, "STATE_ON", 4),
            estop=0,
            interp_state=getattr(linuxcnc, "INTERP_IDLE", 1),
            file="",
        )
        with patch.object(conn_mod, "get_machine_stat", return_value=stat):
            assert svc.get_state() is MachineState.IDLE

    def test_returns_failure_for_unknown_task_state(self):
        """A future LinuxCNC build that adds a state we don't
        know about yet → ``FAILURE`` rather than crashing.
        """
        svc = MachineControlService()
        stat = _fake_stat(task_state=99, estop=0)
        with patch.object(conn_mod, "get_machine_stat", return_value=stat):
            assert svc.get_state() is MachineState.FAILURE

    def test_returns_offline_when_poll_raises(self):
        """A buggy stat impl must not crash the request handler.
        """
        svc = MachineControlService()

        class _BrokenStat:
            def poll(self):
                raise RuntimeError("stat.poll() blew up")

        with patch.object(
            conn_mod, "get_machine_stat", return_value=_BrokenStat()
        ):
            assert svc.get_state() is MachineState.OFFLINE


# ---------------------------------------------------------------------- #
# get_state_snapshot()                                                    #
# ---------------------------------------------------------------------- #


class TestGetStateSnapshot:
    """JSON shape is the wire contract; pin every key."""

    def test_snapshot_shape_is_stable(self):
        """The set of top-level keys is the wire contract; adding
        a key is OK but removing one is a breaking change.
        """
        svc = MachineControlService()
        stat = _fake_stat(
            task_state=getattr(linuxcnc, "STATE_ON", 4),
            estop=0,
            interp_state=getattr(linuxcnc, "INTERP_IDLE", 1),
            file="/tmp/example.gcode",
            homed=[1, 1, 0],
        )
        with patch.object(conn_mod, "get_machine_stat", return_value=stat):
            snap = svc.get_state_snapshot()

        assert set(snap.keys()) == {
            "state",
            "raw_task_state",
            "raw_estop",
            "raw_interp_state",
            "file",
            "homed",
        }

    def test_snapshot_uses_clean_enum_string_for_state(self):
        svc = MachineControlService()
        stat = _fake_stat(
            task_state=getattr(linuxcnc, "STATE_ON", 4),
            estop=0,
            interp_state=getattr(linuxcnc, "INTERP_IDLE", 1),
            file="/tmp/example.gcode",
        )
        with patch.object(conn_mod, "get_machine_stat", return_value=stat):
            snap = svc.get_state_snapshot()
        assert snap["state"] == "loaded"

    def test_snapshot_offline_when_channel_none(self):
        svc = MachineControlService()
        with patch.object(conn_mod, "get_machine_stat", return_value=None):
            snap = svc.get_state_snapshot()
        assert snap["state"] == MachineState.OFFLINE.value
        assert snap["raw_task_state"] == 0
        assert snap["raw_estop"] == 0
        assert snap["raw_interp_state"] == 0
        assert snap["file"] == ""
        assert snap["homed"] == [0, 0, 0]

    def test_snapshot_passes_through_homed_array(self):
        svc = MachineControlService()
        stat = _fake_stat(
            task_state=getattr(linuxcnc, "STATE_ON", 4),
            estop=0,
            interp_state=getattr(linuxcnc, "INTERP_IDLE", 1),
            file="",
            homed=[1, 1, 1],
        )
        with patch.object(conn_mod, "get_machine_stat", return_value=stat):
            snap = svc.get_state_snapshot()
        assert snap["homed"] == [1, 1, 1]


# ---------------------------------------------------------------------- #
# HTTP route                                                              #
# ---------------------------------------------------------------------- #


class TestGetStateEndpoint:
    """``GET /api/v1/modules/machine/state`` returns the snapshot."""

    @staticmethod
    def _build_app() -> FastAPI:
        """Mount the router at the same path the registry uses."""
        app = FastAPI()
        app.include_router(
            state_router,
            prefix="/api/v1/modules/machine_state",
        )
        return app

    def test_endpoint_returns_clean_state(self):
        stat = _fake_stat(
            task_state=getattr(linuxcnc, "STATE_ON", 4),
            estop=0,
            interp_state=getattr(linuxcnc, "INTERP_READING", 2),
            file="/tmp/cut.gcode",
            homed=[1, 1, 1],
        )
        with patch.object(conn_mod, "get_machine_stat", return_value=stat):
            client = TestClient(self._build_app())
            resp = client.get("/api/v1/modules/machine_state/state")

        assert resp.status_code == 200
        body = resp.json()
        assert body["state"] == "running"
        assert body["raw_task_state"] == getattr(linuxcnc, "STATE_ON", 4)
        assert body["raw_estop"] == 0
        assert body["file"] == "/tmp/cut.gcode"
        assert body["homed"] == [1, 1, 1]

    def test_endpoint_returns_offline_when_stat_none(self):
        with patch.object(conn_mod, "get_machine_stat", return_value=None):
            client = TestClient(self._build_app())
            resp = client.get("/api/v1/modules/machine_state/state")

        assert resp.status_code == 200
        assert resp.json()["state"] == "offline"

    def test_endpoint_does_not_leak_linuxcnc_constants_in_schema(self):
        """Guard against an accidental future edit that re-adds an
        ``STATE_*`` / ``INTERP_*`` integer field to the public
        Pydantic schema — those belong on ``raw_*`` fields only.
        """
        from modules.state.router import _StateSnapshot

        fields = _StateSnapshot.model_fields.keys()
        leaked = [
            name for name in fields
            if name.startswith("STATE_") or name.startswith("INTERP_")
        ]
        assert leaked == [], (
            f"_StateSnapshot must not leak linuxcnc constants: {leaked}"
        )


# ---------------------------------------------------------------------- #
# Deprecation warnings                                                    #
# ---------------------------------------------------------------------- #


class TestDeprecatedPassthroughs:
    """Legacy raw accessors still work but emit ``DeprecationWarning``.

    A future PR will migrate every internal caller off the raw
    accessors; until then the warnings serve as a constant
    breadcrumb so the next refactor is well signposted.
    """

    def test_get_machine_stat_warns(self):
        svc = MachineControlService()
        with patch.object(
            conn_mod, "get_machine_stat", return_value=_fake_stat()
        ):
            with pytest.warns(DeprecationWarning, match="get_machine_stat"):
                svc.get_machine_stat()

    def test_get_machine_cmd_warns(self):
        svc = MachineControlService()
        with patch.object(conn_mod, "get_machine_cmd", return_value=None):
            with pytest.warns(DeprecationWarning, match="get_machine_cmd"):
                svc.get_machine_cmd()

    def test_get_machine_error_warns(self):
        svc = MachineControlService()
        with patch.object(conn_mod, "get_machine_error", return_value=None):
            with pytest.warns(DeprecationWarning, match="get_machine_error"):
                svc.get_machine_error()

    def test_is_linuxcnc_connected_warns(self):
        svc = MachineControlService()
        with patch.object(
            conn_mod, "is_linuxcnc_connected", return_value=False
        ):
            with pytest.warns(
                DeprecationWarning, match="is_linuxcnc_connected"
            ):
                svc.is_linuxcnc_connected()
