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
