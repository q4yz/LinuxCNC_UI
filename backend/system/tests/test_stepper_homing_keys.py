"""Klipper's ``homing_speed`` / ``second_homing_speed`` / ``homing_retract_dist`` /
``homing_positive_dir`` / ``full_steps_per_rotation`` / ``gear_ratio`` on every
``[stepper_*]`` (and ``gear_ratio`` / ``full_steps_per_rotation`` on the extruder)."""
from __future__ import annotations

import pytest

from MachineConfigParser import InvalidValueError, MachineConfigParser
from services.machineconfig import AxisBuilder, AxisMappingPolicy
from services.machineconfig.hardware_json_generator import build_hardware_json
from services.machinetemplates.ini_template_generator import render_ini_template

# The user's block, with the commented-out keys switched on.
STEPPER_X = """
[stepper_x]
step_pin: PF12
dir_pin: PF11
enable_pin: !PB3
microsteps: 8
rotation_distance: 40
full_steps_per_rotation:200  #set to 400 for 0.9 degree stepper
endstop_pin: ^PF3
position_min: 0

position_endstop: 250
position_max: 250

homing_speed: 25  #Max 100
homing_retract_dist: 5
homing_positive_dir: true
gear_ratio: 50:17
{extra_x}
"""

REST = """
[mcu]
connection: remora-spi

[stepper_y]
step_pin: PG0
dir_pin: PG1
endstop_pin: PG9
microsteps: 16
rotation_distance: 40
position_endstop: 0
position_max: 250
{extra_y}

[stepper_z]
step_pin: PF11
dir_pin: PG3
endstop_pin: PG10
microsteps: 16
rotation_distance: 8
position_endstop: 0
position_max: 250

[estop]
"""


def _cfg(extra_x="", extra_y="", stepper_x=STEPPER_X):
    return REST.format(extra_y=extra_y) + stepper_x.format(extra_x=extra_x)


_FIELDS = {"SCALE": "scale", "HOME_SEARCH_VEL": "home_search_vel", "HOME_LATCH_VEL": "home_latch_vel",
           "HOME_OFFSET": "home_offset", "HOME": "home_position"}


def _joint(cfg: str, letter: str):
    graph = MachineConfigParser().parse_string(cfg)
    axes = AxisBuilder(graph, policy=AxisMappingPolicy.SPLIT_INTO_MULTIPLE_JOINTS).build()
    render_ini_template("t", axes)  # renders
    return next(a for a in axes if a.letter.upper() == letter).joints[0]


def _value(joint, key: str) -> float:
    return float(getattr(joint, _FIELDS[key]))


def test_the_users_stepper_x_block():
    joint = _joint(_cfg(), "X")
    # 8 microsteps * 200 full steps * 50/17 / 40 mm
    assert _value(joint, "SCALE") == pytest.approx(8 * 200 * 50 / 17 / 40, rel=1e-4)
    assert _value(joint, "HOME_SEARCH_VEL") == 25.0
    assert _value(joint, "HOME_LATCH_VEL") == 25.0  # no second_homing_speed: as before
    assert _value(joint, "HOME_OFFSET") == 250.0
    assert _value(joint, "HOME") == 245.0  # 5 mm back off the switch


def test_second_homing_speed_is_the_latch():
    joint = _joint(_cfg(extra_x="second_homing_speed: 5"), "X")
    assert _value(joint, "HOME_SEARCH_VEL") == 25.0 and _value(joint, "HOME_LATCH_VEL") == 5.0


def test_homing_retract_dist_sets_the_back_off():
    joint = _joint(_cfg().replace("homing_retract_dist: 5", "homing_retract_dist: 12"), "X")
    assert _value(joint, "HOME") == 238.0


def test_homing_positive_dir_overrides_the_end_of_travel():
    # Y's switch is at 0 (negative by default); positive_dir flips search,
    # latch and the back-off.
    default = _joint(_cfg(), "Y")
    assert _value(default, "HOME_SEARCH_VEL") < 0 and _value(default, "HOME") == 5.0
    flipped = _joint(_cfg(extra_y="homing_positive_dir: true\nhoming_speed: 30"), "Y")
    assert _value(flipped, "HOME_SEARCH_VEL") == 30.0 and _value(flipped, "HOME_LATCH_VEL") == 30.0
    assert _value(flipped, "HOME") == -5.0
    negative = _joint(_cfg().replace("homing_positive_dir: true", "homing_positive_dir: false"), "X")
    assert _value(negative, "HOME_SEARCH_VEL") == -25.0 and _value(negative, "HOME") == 255.0


def test_chained_gear_ratio():
    joint = _joint(_cfg().replace("gear_ratio: 50:17", "gear_ratio: 80:16, 3:1"), "X")
    assert _value(joint, "SCALE") == pytest.approx(8 * 200 * 15 / 40)


@pytest.mark.parametrize("bad", ["gear_ratio: 50", "gear_ratio: 50:0", "gear_ratio: a:b", "homing_positive_dir: maybe"])
def test_bad_values(bad):
    key = bad.split(":", 1)[0]
    cfg = _cfg().replace(next(l for l in STEPPER_X.splitlines() if l.startswith(key)), bad)
    with pytest.raises(InvalidValueError):
        MachineConfigParser().parse_string(cfg)


def test_keys_reach_hardware_json():
    payload = build_hardware_json(MachineConfigParser().parse_string(_cfg(extra_x="second_homing_speed: 5")), "t")
    x = next(j for j in payload["joints"] if j["id"] == "stepper_x")
    assert x["gear_ratio"] == pytest.approx(2.9412)
    assert x["homing_speed"] == 25.0 and x["second_homing_speed"] == 5.0
    assert x["homing_retract_dist"] == 5.0 and x["homing_positive_dir"] is True
    assert x["full_steps_per_rotation"] == 200


def test_extruder_gear_ratio_and_full_steps():
    extruder = """
[extruder]
step_pin: PE2
dir_pin: PE3
microsteps: 16
rotation_distance: 22.6789511
gear_ratio: 50:10
full_steps_per_rotation: 400
heater_pin: PA2
sensor_type: Generic 3950
sensor_pin: PF4
control: pid
pid_Kp: 22
pid_Ki: 1
pid_Kd: 100
min_temp: 0
max_temp: 280
"""
    joint = _joint(_cfg() + extruder, "A")
    assert _value(joint, "SCALE") == pytest.approx(16 * 400 * 5 / 22.6789511, rel=1e-4)
