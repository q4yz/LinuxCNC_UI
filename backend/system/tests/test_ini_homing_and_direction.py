"""machine.ini: homing direction, motor direction and subroutine path.

* ``HOME_SEARCH_VEL``/``HOME_LATCH_VEL`` point toward the switch: a switch
  at the *min* end of travel homes with a negative velocity.
* An inverted ``dir_pin`` (``!PF12``) becomes a negative ``SCALE`` — the
  same on every board (Remora's firmware cannot invert a pin; parport no
  longer uses ``-out-invert`` for DIR).
* ``[RS274NGC] SUBROUTINE_PATH`` points at ``macros/`` so ``o<name> call``
  finds the macros and probing cycles.
"""
from __future__ import annotations

from machineconfig_parser import MachineConfigParser
from services.machineconfig.axis_builder import AxisBuilder, AxisMappingPolicy, stepgen_scale

# The policy machine.ini generation uses (``machinetemplates.generator``).
_POLICY = AxisMappingPolicy.SPLIT_INTO_MULTIPLE_JOINTS

_CONFIG = """
[stepper_x]
step_pin: PF13
dir_pin: PF12
microsteps: 16
rotation_distance: 40.0
endstop_pin: PG6
position_min: 0
position_endstop: 0
position_max: 300.0
homing_speed: 50

[stepper_y]
step_pin: PG0
dir_pin: !PG1
microsteps: 16
rotation_distance: 40.0
endstop_pin: PG9
position_min: -620
position_endstop: 0
position_max: 0
homing_speed: 50

[stepper_y1]
step_pin: PF11
dir_pin: PG3
microsteps: 16
rotation_distance: 40.0

[stepper_z]
step_pin: PG2
dir_pin: PG4
microsteps: 16
rotation_distance: 8.0
endstop_pin: PG10
position_min: -5
position_endstop: 130
position_max: 135
homing_speed: 10
"""


def _joints():
    graph = MachineConfigParser().parse_string(_CONFIG)
    joints = {}
    for axis in AxisBuilder(graph, policy=_POLICY).build():
        for joint in axis.joints:
            joints[(axis.letter, joint.joint_number)] = joint
    return graph, joints


def test_switch_at_min_homes_with_negative_velocity():
    _, joints = _joints()
    x = joints[("X", 0)]
    assert (x.home_search_vel, x.home_latch_vel) == (-50.0, -50.0)


def test_switch_at_max_homes_with_positive_velocity():
    _, joints = _joints()
    y = next(j for (letter, _), j in joints.items() if letter == "Y")
    z = next(j for (letter, _), j in joints.items() if letter == "Z")
    assert y.home_search_vel == 50.0  # switch at 0 = max of -620..0
    assert z.home_search_vel == 10.0


def test_gantry_second_motor_homes_the_same_way_as_the_first():
    """``stepper_y1`` inherits Y's (already signed) speed — it must not be
    re-signed into the opposite direction."""
    _, joints = _joints()
    y_joints = [j for (letter, _), j in sorted(joints.items()) if letter == "Y"]
    assert [j.home_search_vel for j in y_joints] == [50.0, 50.0]


def test_inverted_dir_pin_flips_the_scale_sign():
    graph, joints = _joints()
    y_joints = [j for (letter, _), j in sorted(joints.items()) if letter == "Y"]
    expected = stepgen_scale(graph.steppers["y"])
    assert y_joints[0].scale == -expected  # dir_pin: !PG1
    assert y_joints[1].scale == stepgen_scale(graph.steppers["y1"])  # dir_pin: PG3
    assert joints[("X", 0)].scale > 0


def test_ini_carries_signed_values_and_the_subroutine_path():
    from domain_file_services import paths
    from services.machinetemplates.ini_template_generator import render_ini_template

    graph, _ = _joints()
    ini = render_ini_template("t", AxisBuilder(graph, policy=_POLICY).build())
    assert f"SUBROUTINE_PATH = {paths.MACROS_DIR.as_posix()}" in ini
    assert f"USER_M_PATH = {paths.M_CODES_DIR.as_posix()}" in ini
    assert "HOME_SEARCH_VEL = -50.0" in ini
    assert "SCALE = -80.0" in ini  # 16 * 200 / 40, inverted
