"""``[extruder]`` / ``[heater_bed]`` ``max_power`` (the duty ceiling) and the
extruder's ``min_extrude_temp`` (the Remora ``extruder`` component's
cold-extrusion guard -> ``halui.abort``)."""
from __future__ import annotations

import pytest

from MachineConfigParser import InvalidValueError, MachineConfigParser
from services.halcompiler import compile_machine_hal, render_webgui_connections
from services.machineconfig.hardware_json_generator import build_hardware_json

PRINTER = open("tests/fixtures/profiles/full_klipper.cfg").read()


def _with(extruder_extra="", bed_extra=""):
    cfg = PRINTER.replace("[extruder]\n", "[extruder]\n" + extruder_extra, 1)
    return cfg.replace("[heater_bed]\n", "[heater_bed]\n" + bed_extra, 1)


def _payload(cfg):
    return build_hardware_json(MachineConfigParser().parse_string(cfg), "m")


def _tool(payload, tool_id):
    return next(t for t in payload["tools"] if t["id"] == tool_id)


def test_keys_reach_hardware_json():
    payload = _payload(_with("max_power: 0.8\nmin_extrude_temp: 190\n", "max_power: 0.6\n"))
    assert _tool(payload, "heater_extruder")["max_power"] == 0.8
    assert _tool(payload, "heater_extruder")["min_extrude_temp"] == 190.0
    assert _tool(payload, "heater_bed")["max_power"] == 0.6


@pytest.mark.parametrize("bad", ["max_power: 0", "max_power: 1.5", "max_power: full"])
def test_max_power_must_be_above_0_at_most_1(bad):
    with pytest.raises(InvalidValueError):
        MachineConfigParser().parse_string(_with(bad + "\n"))


def test_min_extrude_temp_is_extruder_only():
    from MachineConfigParser import ConfigValidationError

    with pytest.raises(ConfigValidationError):
        MachineConfigParser().parse_string(_with(bed_extra="min_extrude_temp: 100\n"))


def test_max_power_is_the_pid_ceiling():
    from services.machineconfig import AxisBuilder, AxisMappingPolicy
    from services.machinetemplates.ini_template_generator import render_ini_template

    cfg = _with("max_power: 0.8\n")
    payload = _payload(cfg)
    axes = AxisBuilder(MachineConfigParser().parse_string(cfg), policy=AxisMappingPolicy.SPLIT_INTO_MULTIPLE_JOINTS).build()
    ini = render_ini_template("m", axes, payload["tools"])
    sections = {s.split("]", 1)[0]: s for s in ini.split("\n[")}
    cvmax = [line for s in sections.values() for line in s.splitlines() if line.startswith("PID_CVMAX")]
    assert cvmax == ["PID_CVMAX = 80.0"]  # the extruder: 0.8 of 100 %


def test_cold_extrusion_guard_in_machine_hal_and_webgui():
    payload = _payload(_with("min_extrude_temp: 190\n"))
    joint = next(j["joint_number"] for j in payload["joints"] if j["id"] == "heater_extruder")
    hal = compile_machine_hal(payload).splitlines()
    assert "loadrt extruder names=extruder-heater_extruder" in hal
    assert "addf extruder-heater_extruder servo-thread" in hal
    assert "setp extruder-heater_extruder.min-extrude-temp 190" in hal
    assert "net extruder-PV => extruder-heater_extruder.current-temp" in hal
    assert f"net heater_extruder-vel-cmd joint.{joint}.vel-cmd => extruder-heater_extruder.vel-cmd" in hal
    # homing sets the extruder position in place (a vel-cmd spike): ignored
    assert f"net heater_extruder-homing joint.{joint}.homing => extruder-heater_extruder.homing" in hal
    webgui = render_webgui_connections(payload).splitlines()
    assert "net heater_extruder-cold-extrude extruder-heater_extruder.cold-extrude => halui.abort" in webgui
    # the guard runs after motion in the servo thread
    lines = [l for l in hal if l.startswith("addf ")]
    assert lines.index("addf extruder-heater_extruder servo-thread") > lines.index("addf motion-controller servo-thread")


def test_default_min_extrude_temp_and_no_guard_for_the_bed():
    payload = _payload(PRINTER)
    hal = compile_machine_hal(payload)
    assert "setp extruder-heater_extruder.min-extrude-temp 170" in hal
    assert "extruder-heater_bed" not in hal
    assert hal.count("halui.abort") == 0  # only in webgui_connections.hal
