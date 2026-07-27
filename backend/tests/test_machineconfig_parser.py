"""Tests for the strict Klipper configuration parser."""

from __future__ import annotations

import pytest

from modules.machineconfig.models import EndstopSwitch, Stepper
from modules.machineconfig.parser import (
    MachineConfigParser,
    UndefinedKeywordError,
    UnknownStepperError,
)


def test_invalid_keyword_reports_section_and_key() -> None:
    """The parser demonstrates the zero-tolerance keyword contract."""

    config = """
[stepper_x]
step_pin: X_STEP
unexpected_pin: X_BAD
"""

    with pytest.raises(UndefinedKeywordError) as exc_info:
        MachineConfigParser().parse_string(config)

    assert exc_info.value.section == "stepper_x"
    assert exc_info.value.key == "unexpected_pin"
    assert "unexpected_pin" in str(exc_info.value)


def test_builds_linked_object_graph_and_ignores_mcu() -> None:
    config = """
[mcu controller]
serial: /dev/ttyACM0
restart_method: command

[printer]
kinematics: cartesian
max_velocity: 250
max_accel: 1200
minimum_cruise_ratio: 0.5

[endstop_switch y_max]
stepper: y
pin: ^PA1
position: 200
type: limit

[stepper_y]
step_pin: PB1
dir_pin: PB2
enable_pin: !PB3
rotation_distance: 40
microsteps: 16
position_max: 200

[extruder]
step_pin: PA4
pid_Kp: 22.2

[heater_bed]
heater_pin: PA5
max_temp: 120

[spindle]
pwm_pin: PA6
max_rpm: 24000
"""

    machine = MachineConfigParser().parse_string(config)

    stepper = machine.steppers["y"]
    switch = machine.endstop_switches["y_max"]
    assert isinstance(stepper, Stepper)
    assert isinstance(switch, EndstopSwitch)
    assert switch.stepper is stepper
    assert stepper.endstops == [switch]
    assert machine.printer is not None
    assert machine.printer.max_velocity == 250.0
    assert machine.extruder is not None
    assert machine.extruder.pid_Kp == 22.2
    assert machine.heater_bed is not None
    assert machine.spindle is not None


def test_endstop_unknown_target_is_rejected() -> None:
    config = """
[endstop_switch y_max]
stepper: y
pin: PA1
"""

    with pytest.raises(UnknownStepperError, match="unknown stepper 'y'"):
        MachineConfigParser().parse_string(config)
