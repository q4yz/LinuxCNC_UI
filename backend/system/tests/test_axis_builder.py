"""AxisBuilder — the joint-numbering bug: the extruder axis must
continue the same global sequence every other joint uses.

`hardware_json_generator.py` already gets this right (its own,
separate joint-numbering pass) — this file is specifically about
`AxisBuilder`, the parallel implementation `render_ini_template`
(`machine.ini` generation) depends on, which used the extruder axis's
own *local* joint count instead of the shared allocator and so handed
out `[JOINT_0]` twice on any machine with both a Cartesian X axis and
an extruder.
"""

from __future__ import annotations

from machineconfig_parser import MachineConfigParser
from services.machineconfig.axis_builder import AxisBuilder, AxisMappingPolicy

_CONFIG = """
[stepper_x]
step_pin: PF13
dir_pin: PF12
rotation_distance: 40.0
position_max: 300.0

[stepper_y]
step_pin: PG0
dir_pin: PG1
rotation_distance: 40.0
position_max: 300.0

[stepper_z]
step_pin: PG2
dir_pin: PG3
rotation_distance: 40.0
position_max: 300.0

[extruder]
step_pin: PC9
dir_pin: PC8
rotation_distance: 33.5
heater_pin: PE3
sensor_pin: PA1
control: pid
pid_Kp: 22.2
pid_Ki: 1.08
pid_Kd: 114
min_temp: 0
max_temp: 250
"""


def test_extruder_joint_continues_the_global_sequence():
    """The real bug: X/Y/Z claim 0/1/2, so the extruder must be 3 —
    not 0, which would collide with X's own `[JOINT_0]`/
    `remora.joint.0.*`."""
    graph = MachineConfigParser().parse_string(_CONFIG)
    axes = AxisBuilder(graph, policy=AxisMappingPolicy.SPLIT_INTO_MULTIPLE_JOINTS).build()

    by_letter = {axis.letter: axis for axis in axes}
    assert [j.joint_number for j in by_letter["X"].joints] == [0]
    assert [j.joint_number for j in by_letter["Y"].joints] == [1]
    assert [j.joint_number for j in by_letter["Z"].joints] == [2]
    assert [j.joint_number for j in by_letter["A"].joints] == [3]

    # No two joints anywhere share a number.
    all_numbers = [j.joint_number for axis in axes for j in axis.joints]
    assert len(all_numbers) == len(set(all_numbers)), all_numbers


_GANTRY_CONFIG = """
[stepper_x]
step_pin: PF13
dir_pin: PF12
rotation_distance: 40.0
position_max: 300.0

[stepper_y]
step_pin: PG0
dir_pin: PG1
rotation_distance: 40.0
position_min: -2.0
position_max: 497.7
position_endstop: 497.7
homing_speed: 10.0

[stepper_y1]
step_pin: PG4
dir_pin: PG5
rotation_distance: 40.0

[stepper_z]
step_pin: PG2
dir_pin: PG3
rotation_distance: 40.0
position_max: 300.0
"""


def test_gantry_second_joint_inherits_travel_limits_from_the_primary_stepper():
    """Klipper convention: only the primary stepper on a gantry axis
    (``stepper_y``) declares ``position_min``/``position_max``/
    ``position_endstop``/``homing_speed`` — the secondary stepper
    (``stepper_y1``) only carries pin/motor fields, relying on the
    same rail. Without a fallback, the second joint used to render
    ``MIN_LIMIT``/``MAX_LIMIT``/``HOME``/``HOME_OFFSET`` as 0 instead
    of copying the first joint's real travel limits."""
    graph = MachineConfigParser().parse_string(_GANTRY_CONFIG)
    axes = AxisBuilder(graph, policy=AxisMappingPolicy.SPLIT_INTO_MULTIPLE_JOINTS).build()

    by_letter = {axis.letter: axis for axis in axes}
    y_joints = by_letter["Y"].joints
    assert len(y_joints) == 2
    primary, secondary = y_joints

    assert primary.min_limit == -2.0
    assert primary.max_limit == 497.7
    assert primary.home_position == 497.7
    assert primary.home_offset == 497.7
    assert primary.home_search_vel == 10.0
    assert primary.home_latch_vel == 10.0

    # The bug: these used to be 0.0 on the secondary joint because it
    # only reflected `stepper_y1`'s own (absent) fields.
    assert secondary.min_limit == primary.min_limit
    assert secondary.max_limit == primary.max_limit
    assert secondary.home_position == primary.home_position
    assert secondary.home_offset == primary.home_offset
    assert secondary.home_search_vel == primary.home_search_vel
    assert secondary.home_latch_vel == primary.home_latch_vel


def test_multiple_extruders_each_get_a_distinct_continuing_number():
    """Two `[extruder]`-shaped sections (`[extruder]` + a second
    heater-with-a-stepper) must not both land on the same number —
    same collision class, multiplied."""
    config = _CONFIG + """
[extruder1]
step_pin: PC7
dir_pin: PC6
rotation_distance: 33.5
heater_pin: PE4
sensor_pin: PA2
control: pid
pid_Kp: 22.2
pid_Ki: 1.08
pid_Kd: 114
min_temp: 0
max_temp: 250
"""
    graph = MachineConfigParser().parse_string(config)
    axes = AxisBuilder(graph, policy=AxisMappingPolicy.SPLIT_INTO_MULTIPLE_JOINTS).build()

    by_letter = {axis.letter: axis for axis in axes}
    a_numbers = [j.joint_number for j in by_letter["A"].joints]
    assert a_numbers == [3, 4]
