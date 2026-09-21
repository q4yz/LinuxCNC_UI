"""Tests for the hardware-layer abstractions.

The OOP refactor split the historical monolithic machine module
into :mod:`modules.axis`, :mod:`modules.state` and
:mod:`modules.program`; the old ``machine.service``
entry point no longer exists. Command-dispatch for axis motion now
lives on :class:`services.AxisService.AxisService`, machine-task
state on :class:`services.StateService.StateService`, and program
lifecycle on :class:`services.ProgramService.ProgramService`. The
hardware-layer :class:`services.machine_service.MachineService`
remains the single gateway to the NML command channel that all of
them dispatch through.

This suite covers:

  * :class:`DeviceConfigMapper` — .cfg parsing, endstop-pin extraction,
    fallback pins.
  * :class:`MachineService` (hardware-layer) — ``get_endstop`` and
    ``get_endstop_state_subscription`` — including the M114 fallback
    when LinuxCNC is offline.
  * :func:`execute_gcode` — happy path + 503 when channels are
    offline.

``HalSubscriptionManager`` (interval-poll HAL pin subscriptions) was
removed — this app only ever reads HAL pins on request (REST-style,
see the 1Hz base-thread snapshot), it never needed a standing poll
loop, and the class had zero production callers.
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
conn_mod = importlib.import_module("hardware.Connection")
# ``hardware.Connection`` is itself a package now (core/channel_stat/
# channel_error/channel_cmd) — ``execute_gcode`` is *defined* in
# ``channel_cmd``, so its internal ``get_stat_channel()``/
# ``get_cmd_channel()`` calls resolve names bound in *that* module's
# own namespace, not whatever ``patch.object(conn_mod, ...)`` touches
# on the package facade. Patch where it's used: ``cmd_mod``, not
# ``conn_mod``.
cmd_mod = importlib.import_module("hardware.Connection.channel_cmd")
from hardware.Connection import (
    DeviceConfigMapper,
    execute_gcode,
)
from services.MachineService import MachineService


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
# MachineService (hardware-layer)                                       #
# ────────────────────────────────────────────────────────────────────── #


class TestHardwareLayerMachineService:
    """``MachineService`` composes mapper + hal manager.

    Distinct from ``machine.service.MachineService``
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
        with patch.object(cmd_mod, "get_stat_channel", return_value=fake_stat):
            with patch.object(cmd_mod, "get_cmd_channel", return_value=fake_cmd):
                result = execute_gcode("G28")

        assert result == {"status": "success", "gcode": "G28"}

    def test_execute_gcode_raises_503_when_channels_offline(self):
        """LinuxCNC not running → ``get_machine_cmd`` returns
        ``None`` → 503. The router surfaces this as a clear
        "service unavailable" rather than crashing the worker.
        """
        from fastapi import HTTPException

        with patch.object(cmd_mod, "get_stat_channel", return_value=None):
            with patch.object(cmd_mod, "get_cmd_channel", return_value=None):
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
        with patch.object(cmd_mod, "get_stat_channel", return_value=fake_stat):
            with patch.object(cmd_mod, "get_cmd_channel", return_value=fake_cmd):
                execute_gcode("G28")

        assert mode_called == []
