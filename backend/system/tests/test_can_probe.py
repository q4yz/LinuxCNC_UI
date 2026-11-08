"""Z homed on the probe — Klipper's ``probe:z_virtual_endstop`` — also
with the probe on a CAN toolhead node. No Z home switch: the probe only
ever triggers during a probe move (the machine backend's G38.2), which
is what LinuxCNC requires ("probe tripped during non-probe move")."""
from __future__ import annotations

import pytest

from MachineConfigParser import InvalidValueError, MachineConfigParser
from services.halcompiler import compile_machine_hal, validate_machine
from services.machineconfig.hardware_json_generator import build_hardware_json

CFG = """
[mcu]
connection: remora-spi

[mcu sb2209]
connection: remora-can
canbus_uuid: 0E0D81E4210C

[stepper_x]
step_pin: PF13
dir_pin: PF12
endstop_pin: {x_endstop}
position_endstop: 0
position_max: 250

[stepper_y]
step_pin: PG0
dir_pin: PG1
endstop_pin: PG9
position_endstop: 0
position_max: 250

[stepper_z]
step_pin: PF11
dir_pin: PG3
endstop_pin: {z_endstop}
position_endstop: 0
position_max: 250

[estop]

[probe]
pin: {probe}
{extra}
"""
OVERRIDE = "[duplicate_pin_override]\npins: sb2209:PB6\n"


def _payload(probe="!sb2209:PB6", z_endstop="!sb2209:PB6", x_endstop="PG6", extra=OVERRIDE):
    src = CFG.format(probe=probe, z_endstop=z_endstop, x_endstop=x_endstop, extra=extra)
    return build_hardware_json(MachineConfigParser().parse_string(src), "trident")


def _codes(payload):
    return {d.code for d in validate_machine(payload) if d.is_error}


def _ini(src_extra=""):
    from services.machineconfig import AxisBuilder, AxisMappingPolicy
    from services.machinetemplates.ini_template_generator import render_ini_template

    graph = MachineConfigParser().parse_string(CFG.format(
        probe="!sb2209:PB6", z_endstop="probe:z_virtual_endstop", x_endstop="PG6", extra=src_extra))
    return render_ini_template("t", AxisBuilder(graph, policy=AxisMappingPolicy.SPLIT_INTO_MULTIPLE_JOINTS).build())


@pytest.mark.parametrize("z_endstop", ["probe:z_virtual_endstop", "!sb2209:PB6"])
def test_z_homes_on_the_probe(z_endstop):
    payload = _payload(z_endstop=z_endstop, extra="")
    assert _codes(payload) == set()
    assert payload["z_virtual_endstop"] == {"speed": 5.0, "second_speed": 2.5, "retract": 5.0, "distance": 255.0}
    hal = compile_machine_hal(payload)
    # The probe is the probe only: no Z home switch, no shared pin.
    assert "joint.2.home-sw-in" not in hal
    assert any(l.endswith("motion.probe-input") for l in hal.splitlines())
    assert "sb2209:PB6" not in payload["duplicate_pin_overrides"]


def test_z_joint_homes_in_place_at_position_endstop():
    import re
    ini = _ini()
    joint = ini.split("[JOINT_2]", 1)[1].split("\n\n", 1)[0]
    assert re.search(r"HOME_SEARCH_VEL = 0(\.0)?\n", joint) and re.search(r"HOME_LATCH_VEL = 0(\.0)?\n", joint)
    assert "HOME_OFFSET = 0.0" in joint and "\nHOME = 0.0" in joint


def test_klipper_speeds():
    src = CFG.format(probe="!sb2209:PB6", z_endstop="probe:z_virtual_endstop", x_endstop="PG6", extra="").replace(
        "position_max: 250\n\n[estop]", "position_max: 250\nhoming_speed: 8\nsecond_homing_speed: 2\nhoming_retract_dist: 3\n\n[estop]")
    payload = build_hardware_json(MachineConfigParser().parse_string(src), "t")
    assert payload["z_virtual_endstop"] == {"speed": 8.0, "second_speed": 2.0, "retract": 3.0, "distance": 255.0}


def test_virtual_endstop_needs_a_probe():
    src = CFG.format(probe="!sb2209:PB6", z_endstop="probe:z_virtual_endstop", x_endstop="PG6", extra="")
    src = src.replace("[probe]\npin: !sb2209:PB6\n", "")
    with pytest.raises(InvalidValueError, match="probe"):
        build_hardware_json(MachineConfigParser().parse_string(src), "trident")


def test_virtual_endstop_is_for_z_only():
    with pytest.raises(InvalidValueError, match="Z stepper"):
        _payload(x_endstop="probe:z_virtual_endstop", extra="")


def test_probe_on_a_node_without_homing_on_it():
    assert "E_CAN_NODE_PIN" in _codes(_payload(probe="sb2209:PB5", z_endstop="PG10", extra=""))


def test_probe_sharing_another_endstop_needs_the_override():
    payload = _payload(probe="PB7", z_endstop="PG10", x_endstop="PB7", extra="")
    assert "E_PIN_CONFLICT" in _codes(payload)
