"""The probe as Z endstop on a CAN toolhead node (Klipper's "probe as
virtual Z endstop"): one node input feeds homing and motion.probe-input."""
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


def _probe_signal(hal):
    line = next(l for l in hal.splitlines() if l.endswith("motion.probe-input"))
    return line.split()[1]


def test_probe_as_z_endstop_on_a_node():
    payload = _payload()
    assert _codes(payload) == set()
    hal = compile_machine_hal(payload)
    signal = _probe_signal(hal)
    # The same signal homes Z: one node input, no new input type.
    assert f"net {signal} => joint.2.home-sw-in" in hal


def test_the_override_is_added_for_the_z_endstop():
    payload = _payload(extra="")
    assert "sb2209:PB6" in payload["duplicate_pin_overrides"]
    assert _codes(payload) == set()


def test_klipper_virtual_endstop():
    payload = _payload(z_endstop="probe:z_virtual_endstop", extra="")
    assert _codes(payload) == set()
    hal = compile_machine_hal(payload)
    assert f"net {_probe_signal(hal)} => joint.2.home-sw-in" in hal


def test_virtual_endstop_needs_a_probe():
    src = CFG.format(probe="!sb2209:PB6", z_endstop="probe:z_virtual_endstop", x_endstop="PG6", extra="")
    src = src.replace("[probe]\npin: !sb2209:PB6\n", "")
    with pytest.raises(InvalidValueError, match="probe"):
        build_hardware_json(MachineConfigParser().parse_string(src), "trident")


def test_probe_on_a_node_without_an_endstop_there():
    assert "E_CAN_NODE_PIN" in _codes(_payload(probe="sb2209:PB5", extra=""))


def test_probe_sharing_another_endstop_needs_the_override():
    # Only the Z endstop gets the shared pin automatically.
    payload = _payload(probe="sb2209:PB7", z_endstop="PG10", x_endstop="sb2209:PB7", extra="")
    assert "E_PIN_CONFLICT" in _codes(payload)
