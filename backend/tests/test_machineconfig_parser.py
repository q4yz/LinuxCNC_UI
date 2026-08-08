"""Tests for the strict Klipper configuration parser."""

from __future__ import annotations

import pytest

from modules.machineconfig.models import EndstopSwitch, Stepper
from modules.machineconfig.parser import (
    ConfigValidationError,
    DuplicateStepperPinError,
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


# ---------------------------------------------------------------------- #
# Duplicate-stepper-pin rule (issue #99)                                 #
# ---------------------------------------------------------------------- #


def test_duplicate_stepper_pin_step_pin_is_rejected() -> None:
    """Two steppers sharing ``step_pin`` raise DuplicateStepperPinError."""

    config = """
[stepper_x]
step_pin: PA0
dir_pin: PA1
enable_pin: !PA2

[stepper_y]
step_pin: PA0
dir_pin: PA3
enable_pin: !PA4
"""

    with pytest.raises(DuplicateStepperPinError) as exc_info:
        MachineConfigParser().parse_string(config)

    exc = exc_info.value
    assert exc.pin == "PA0"
    assert exc.pin_key == "step_pin"
    assert exc.section == "y"
    assert exc.axes == ["x", "y"]
    assert exc.kind == "duplicate_stepper_pin"
    # ``to_dict`` is the contract surface for the HTTP layer.
    payload = exc.to_dict()
    assert payload["section"] == "y"
    assert payload["key"] == "step_pin"
    assert payload["line"] is None
    assert payload["kind"] == "duplicate_stepper_pin"
    assert "PA0" in payload["message"]


def test_duplicate_stepper_pin_dir_pin_is_rejected() -> None:
    """Two steppers sharing ``dir_pin`` raise DuplicateStepperPinError."""

    config = """
[stepper_x]
step_pin: PA0
dir_pin: PA1
enable_pin: !PA2

[stepper_y]
step_pin: PA3
dir_pin: PA1
enable_pin: !PA4
"""

    with pytest.raises(DuplicateStepperPinError) as exc_info:
        MachineConfigParser().parse_string(config)

    exc = exc_info.value
    assert exc.pin == "PA1"
    assert exc.pin_key == "dir_pin"
    assert exc.axes == ["x", "y"]


def test_duplicate_stepper_pin_enable_pin_is_rejected() -> None:
    """Two steppers sharing ``enable_pin`` raise DuplicateStepperPinError."""

    config = """
[stepper_x]
step_pin: PA0
dir_pin: PA1
enable_pin: !PA2

[stepper_y]
step_pin: PA3
dir_pin: PA4
enable_pin: !PA2
"""

    with pytest.raises(DuplicateStepperPinError) as exc_info:
        MachineConfigParser().parse_string(config)

    exc = exc_info.value
    assert exc.pin == "!PA2"
    assert exc.pin_key == "enable_pin"
    assert exc.axes == ["x", "y"]


def test_duplicate_stepper_pin_endstop_pin_is_rejected() -> None:
    """Two steppers sharing ``endstop_pin`` raise DuplicateStepperPinError."""

    config = """
[stepper_x]
step_pin: PA0
dir_pin: PA1
enable_pin: !PA2
endstop_pin: ^PA3

[stepper_y]
step_pin: PA4
dir_pin: PA5
enable_pin: !PA6
endstop_pin: ^PA3
"""

    with pytest.raises(DuplicateStepperPinError) as exc_info:
        MachineConfigParser().parse_string(config)

    exc = exc_info.value
    assert exc.pin == "^PA3"
    assert exc.pin_key == "endstop_pin"
    assert exc.axes == ["x", "y"]


def test_duplicate_stepper_pin_is_a_config_validation_error() -> None:
    """DuplicateStepperPinError inherits from ConfigValidationError.

    The HTTP exception handler in ``router.py`` registers against the
    base class so every subclass — including the new
    ``DuplicateStepperPinError`` — flows through the same structured
    response shape. The isinstance guard below keeps that contract
    honest when the class hierarchy grows.
    """

    assert issubclass(DuplicateStepperPinError, ConfigValidationError)


def test_distinct_stepper_pins_for_multi_motor_y_are_accepted() -> None:
    """Multi-motor Y uses distinct pins and must parse cleanly.

    Regression guard: a naïve check that flagged every same-axis
    collision would reject the legitimate dual-motor case.
    """

    config = """
[stepper_x]
step_pin: PA0
dir_pin: PA1
enable_pin: !PA2

[stepper_y]
step_pin: PA3
dir_pin: PA4
enable_pin: !PA5

[stepper_y1]
step_pin: PA6
dir_pin: PA7
enable_pin: !PA8

[stepper_z]
step_pin: PA9
dir_pin: PA10
enable_pin: !PA11
"""

    graph = MachineConfigParser().parse_string(config)
    assert sorted(graph.steppers.keys()) == ["x", "y", "y1", "z"]
