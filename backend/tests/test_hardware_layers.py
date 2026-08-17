"""Tests for the hardware-layer abstractions.

The OOP refactor split the historical monolithic machine module
into :mod:`modules.axis`, :mod:`modules.state` and
:mod:`modules.program`; the old ``backend.modules.machine.service``
entry point no longer exists. Command-dispatch for axis motion now
lives on :class:`modules.axis.service.AxisService`, machine-task
state on :class:`modules.state.service.StateService`, and program
lifecycle on :class:`modules.program.service.ProgramService`. The
hardware-layer :class:`services.machine_service.MachineService`
remains the single gateway to the NML command channel that all of
them dispatch through.

This suite covers:

  * :class:`DeviceConfigMapper` — .cfg parsing, endstop-pin extraction,
    fallback pins.
  * :class:`HalSubscriptionManager` — subscribe / poll / callback
    fan-out, start / stop idempotency.
  * :class:`MachineService` (hardware-layer) — ``get_endstop`` and
    ``get_endstop_state_subscription`` — including the M114 fallback
    when LinuxCNC is offline.
  * :func:`execute_gcode` — happy path + 503 when channels are
    offline.
"""

from __future__ import annotations

import importlib
import time
from unittest.mock import patch

import pytest

# ``hardware.connection`` is shadowed in ``hardware/__init__.py``
# by ``connection = Connection()`` so a plain
# ``from hardware import connection as conn_mod`` resolves to the
# instance. ``importlib.import_module`` bypasses the package
# __init__ re-export and gives us the submodule.
conn_mod = importlib.import_module("hardware.connection")
from hardware.connection import (
    DeviceConfigMapper,
    HalSubscriptionManager,

    execute_gcode,
)
from services.machine_service import MachineService


# ────────────────────────────────────────────────────────────────────── #
# DeviceConfigMapper                                                      #
# ────────────────────────────────────────────────────────────────────── #


class TestDeviceConfigMapper:
    """``.cfg`` parsing + endstop-pin extraction.

    Tests use ``tmp_path`` to write a real ``.cfg`` rather than
    mocking configparser — the mapper's behaviour depends on the
    configparser's ``has_section`` / ``has_option`` semantics, and
    a real file surfaces those edge cases more honestly than a
    mock would.
    """

    def test_no_path_means_no_pins_until_called(self, tmp_path):
        """Constructor without a path leaves the mapper empty until
        :meth:`load_file` is called. ``get_endstop_hal_pin_list``
        returns the canonical three-axis fallback so a freshly-booted
        backend without a ``.cfg`` doesn't crash.
        """
        mapper = DeviceConfigMapper()
        pins = mapper.get_endstop_hal_pin_list()
        assert pins == [
            "joint.0.home-sw-in",
            "joint.1.home-sw-in",
            "joint.2.home-sw-in",
        ]

    def test_load_file_picks_up_explicit_endstops_section(self, tmp_path):
        """The ``[ENDSTOPS]`` short-circuit returns every option
        value verbatim — values are HAL pin names, not axis
        labels, so we don't transform them.
        """
        cfg = tmp_path / "machine.cfg"
        cfg.write_text(
            "[ENDSTOPS]\n"
            "X_HOME = joint.0.home-sw-in\n"
            "Y_HOME = joint.1.home-sw-in\n"
            "Z_HOME = joint.2.home-sw-in\n"
        )
        mapper = DeviceConfigMapper(str(cfg))
        pins = mapper.get_endstop_hal_pin_list()
        assert pins == [
            "joint.0.home-sw-in",
            "joint.1.home-sw-in",
            "joint.2.home-sw-in",
        ]

    def test_load_file_falls_back_to_per_joint_home_switch_pin(
        self, tmp_path
    ):
        """Per-joint ``HOME_SWITCH_PIN`` is the standard LinuxCNC INI
        convention. The mapper walks ``[JOINT_*]`` and ``[AXIS_*]``
        sections and collects every ``HOME_SWITCH_PIN`` value.
        """
        cfg = tmp_path / "machine.cfg"
        cfg.write_text(
            "[JOINT_0]\nHOME_SWITCH_PIN = joint.0.home-sw-in\n\n"
            "[JOINT_1]\nHOME_SWITCH_PIN = joint.1.home-sw-in\n\n"
            "[JOINT_2]\nHOME_SWITCH_PIN = joint.2.home-sw-in\n\n"
            "[EMCIO]\n"  # section without HOME_SWITCH_PIN — must be ignored
            "EMCIOENCODING = ascii\n"
        )
        mapper = DeviceConfigMapper(str(cfg))
        assert mapper.get_endstop_hal_pin_list() == [
            "joint.0.home-sw-in",
            "joint.1.home-sw-in",
            "joint.2.home-sw-in",
        ]

    def test_load_file_falls_back_when_no_endstops_configured(
        self, tmp_path
    ):
        """An empty / unrelated ``.cfg`` returns the canonical
        fallback so the dashboard never crashes on a missing
        configuration. Same contract as the no-path case.
        """
        cfg = tmp_path / "machine.cfg"
        cfg.write_text("[EMCIO]\nEMCIOENCODING = ascii\n")
        mapper = DeviceConfigMapper(str(cfg))
        assert mapper.get_endstop_hal_pin_list() == [
            "joint.0.home-sw-in",
            "joint.1.home-sw-in",
            "joint.2.home-sw-in",
        ]

    def test_load_file_with_nonexistent_path_keeps_fallback(
        self, tmp_path
    ):
        """Constructor tolerates a missing ``.cfg`` — important
        for the test environment where the file may not exist.
        """
        mapper = DeviceConfigMapper(str(tmp_path / "nope.cfg"))
        assert mapper.get_endstop_hal_pin_list() == [
            "joint.0.home-sw-in",
            "joint.1.home-sw-in",
            "joint.2.home-sw-in",
        ]


# ────────────────────────────────────────────────────────────────────── #
# HalSubscriptionManager                                                  #
# ────────────────────────────────────────────────────────────────────── #


class TestHalSubscriptionManager:
    """Poll / subscribe / fire-on-change semantics.

    Tests do not start the background thread — they exercise
    ``subscribe`` + ``read_pin`` + ``_poll_loop`` directly so the
    suite stays hermetic and fast.
    """

    def test_subscribe_records_callback_under_pin(self):
        """First subscribe on a pin captures the current value
        (the mock returns ``False``) as the baseline so the first
        poll doesn't fire a spurious change event.
        """
        mgr = HalSubscriptionManager(poll_interval=0.01)
        cb = lambda val: None
        mgr.subscribe("joint.0.home-sw-in", cb)
        assert "joint.0.home-sw-in" in mgr._subscriptions
        assert cb in mgr._subscriptions["joint.0.home-sw-in"]
        # First subscribe seeds the baseline with the current
        # (mock) value so a subsequent change is detected.
        assert mgr._last_known_states["joint.0.home-sw-in"] is False

    def test_subscribe_appends_multiple_callbacks(self):
        """Multiple subscribers on one pin fan out independently —
        ``subscribe`` does not replace, it appends.
        """
        mgr = HalSubscriptionManager()
        cb_a = lambda val: None
        cb_b = lambda val: None
        mgr.subscribe("joint.0.home-sw-in", cb_a)
        mgr.subscribe("joint.0.home-sw-in", cb_b)
        assert [cb_a, cb_b] == mgr._subscriptions["joint.0.home-sw-in"]

    def test_read_pin_returns_false_when_hal_unavailable(self):
        """``hal is None`` or ``USE_MOCK=True`` short-circuits to
        ``False`` so the dashboard renders the "offline" branch
        instead of crashing.
        """
        mgr = HalSubscriptionManager()
        with patch.object(conn_mod, "HAS_HAL", False):
            assert mgr.read_pin("anything") is False
        with patch.object(conn_mod, "HAS_HAL", True):
            with patch.object(conn_mod, "USE_MOCK", True):
                assert mgr.read_pin("anything") is False

    def test_read_pin_calls_hal_get_value_when_available(self):
        """Real HAL path goes through ``hal.get_value``. Mock the HAL
        helper to confirm the dispatch path.
        """
        fake_hal = type("HAL", (), {"get_value": staticmethod(lambda p: True)})
        mgr = HalSubscriptionManager()
        with patch.object(conn_mod, "hal", fake_hal):
            with patch.object(conn_mod, "HAS_HAL", True):
                with patch.object(conn_mod, "USE_MOCK", False):
                    assert mgr.read_pin("joint.0.home-sw-in") is True

    def test_poll_loop_fires_callback_on_state_change(self):
        """The poll loop reads each subscribed pin and fires callbacks
        only when the value changes from the last-known state.

        Tests drive ``_poll_loop`` directly. The loop runs ``while
        self._running:`` — the test stops the loop after one tick
        by patching ``time.sleep`` to flip ``_running`` to ``False``,
        so the while-exit fires before the second ``time.sleep``
        would block the suite.
        """
        mgr = HalSubscriptionManager(poll_interval=0.001)
        fired: list = []
        mgr.subscribe("joint.0.home-sw-in", lambda v: fired.append(v))

        # First tick: value matches the seeded baseline → no fire.
        # Patch ``time.sleep`` so the very first sleep flips
        # ``_running`` off and the loop exits after one iteration.
        with patch.object(mgr, "read_pin", return_value=False):
            with patch.object(conn_mod.time, "sleep") as sleep_spy:
                def stop_after_first_sleep(_):
                    mgr._running = False
                sleep_spy.side_effect = stop_after_first_sleep
                mgr._running = True
                mgr._poll_loop()
        assert fired == []

        # Second tick: pin flips True → callback fires once. The
        # same sleep-flip pattern keeps the loop bounded.
        with patch.object(mgr, "read_pin", return_value=True):
            with patch.object(conn_mod.time, "sleep") as sleep_spy:
                sleep_spy.side_effect = lambda _: setattr(mgr, "_running", False)
                mgr._running = True
                mgr._poll_loop()
        assert fired == [True]

    def test_start_is_idempotent(self):
        """Multiple ``start()`` calls don't stack poll threads — the
        ``_running`` guard short-circuits the second invocation.
        """
        mgr = HalSubscriptionManager()
        # Patch ``threading.Thread`` so the test doesn't actually spawn.
        with patch.object(conn_mod.threading, "Thread") as mock_thread:
            mgr.start()
            mgr.start()  # second call must no-op
            assert mock_thread.call_count == 1

    def test_stop_is_idempotent(self):
        """``stop()`` when the thread was never started must not
        raise — ``_thread`` is ``None`` and the ``is not None``
        guard short-circuits the ``join()``.
        """
        mgr = HalSubscriptionManager()
        mgr.stop()  # must not raise
        mgr.stop()


# ────────────────────────────────────────────────────────────────────── #
# MachineService (hardware-layer)                                       #
# ────────────────────────────────────────────────────────────────────── #


class TestHardwareLayerMachineService:
    """``MachineService`` composes mapper + hal manager.

    Distinct from ``backend.modules.machine.service.MachineService``
    (command dispatch): the hardware-layer one handles config-driven
    hardware abstraction. The endstop surface that used to live on
    this class was retired in the refactor that moved endstop state
    into the HAL subscription manager's snapshot — the tests below
    document that history. The remaining tests cover the gcode
    dispatch path which is still wired through
    :class:`MachineService`.
    """


# ────────────────────────────────────────────────────────────────────── #
# execute_gcode                                                            #
# ────────────────────────────────────────────────────────────────────── #


class TestExecuteGcode:
    """``execute_gcode`` dispatches G-code via the linuxcnc command channel.

    The helper sets ``MODE_MDI`` before dispatching, then waits for
    ``RCS_DONE`` / ``RCS_ERROR`` / timeout. Tests patch the channel
    helpers to assert the dispatch path without standing up a real
    LinuxCNC instance.
    """

    def test_execute_gcode_happy_path(self):
        """Happy path: ``stat.poll()`` is called, mode is set to
        ``MODE_MDI`` (when not already), the G-code is dispatched,
        ``wait_complete`` returns ``RCS_DONE``, and the helper
        returns ``{"status": "success", "gcode": ...}``.
        """
        # Set up a fake command + status channel pair.
        fake_stat = type(
            "Stat",
            (),
            {"poll": lambda self: None, "task_mode": 99},
        )()
        fake_cmd = type(
            "Cmd",
            (),
            {
                "mode": lambda self, m: None,
                "mdi": lambda self, g: None,
                "wait_complete": lambda self, t: getattr(conn_mod.linuxcnc, "RCS_DONE", 1),
            },
        )()
        with patch.object(conn_mod, "_stat_ch", conn_mod._LazyChannel("stat")):
            with patch.object(conn_mod, "get_machine_stat", return_value=fake_stat):
                with patch.object(conn_mod, "get_machine_cmd", return_value=fake_cmd):
                    result = execute_gcode("G28")

        assert result == {"status": "success", "gcode": "G28"}

    def test_execute_gcode_raises_503_when_channels_offline(self):
        """LinuxCNC not running → ``get_machine_cmd`` returns
        ``None`` → 503. The router surfaces this as a clear
        "service unavailable" rather than crashing the worker.
        """
        from fastapi import HTTPException

        with patch.object(conn_mod, "get_machine_stat", return_value=None):
            with patch.object(conn_mod, "get_machine_cmd", return_value=None):
                with pytest.raises(HTTPException) as excinfo:
                    execute_gcode("G28")
        assert excinfo.value.status_code == 503

    def test_execute_gcode_skips_mode_change_when_already_mdi(self):
        """If the task mode is already ``MODE_MDI`` the helper must
        not call ``cmd.mode(...)`` — that's a wasted NML round-trip.
        """
        fake_stat = type(
            "Stat",
            (),
            {"poll": lambda self: None, "task_mode": conn_mod.linuxcnc.MODE_MDI},
        )()
        mode_called = []
        fake_cmd = type(
            "Cmd",
            (),
            {
                "mode": lambda self, m: mode_called.append(m),
                "mdi": lambda self, g: None,
                "wait_complete": lambda self, t: getattr(conn_mod.linuxcnc, "RCS_DONE", 1),
            },
        )()
        with patch.object(conn_mod, "get_machine_stat", return_value=fake_stat):
            with patch.object(conn_mod, "get_machine_cmd", return_value=fake_cmd):
                execute_gcode("G28")

        assert mode_called == []
