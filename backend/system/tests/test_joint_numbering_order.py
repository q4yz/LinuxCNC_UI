"""machine.ini's [JOINT_N] must be the same motor as remora.joint.N.

``hardware.json`` (and every HAL mapper, CoreXY included) numbers joints
in canonical order — X, Y, Z, extruder — whatever order the
``[stepper_*]`` sections are written in. ``AxisBuilder`` used to number
them in declaration order, so a profile with ``[stepper_y]`` first gave
``[JOINT_0]`` stepper_y's SCALE while ``remora.joint.0`` drives
stepper_x: a CoreXY with 16 / 8 microsteps moved wrong, equal values hid it.
"""

from __future__ import annotations

import json
import re

import pytest

from MachineConfigParser import MachineConfigParser
from services.machineconfig.AxisBuilder import AxisBuilder, AxisMappingPolicy
from services.machineconfig.hardware_json_generator import build_hardware_json
from services.machinetemplates.ini_template_generator import render_ini_template

CFG = """
[mcu]
connection: remora-spi
board: BTT MANTA M8P

[machine]
kinematics: {kinematics}
max_velocity: 300
max_accel: 3000

[stepper_y]
step_pin: PF12
dir_pin: PF11
enable_pin: !PB3
microsteps: 8
rotation_distance: 40
position_endstop: 0
position_max: 220

[stepper_x]
step_pin: PE2
dir_pin: PB4
enable_pin: !PC11
microsteps: 16
rotation_distance: 40
position_endstop: 0
position_max: 200

[stepper_z]
step_pin: PD7
dir_pin: PD6
enable_pin: !PF10
microsteps: 8
rotation_distance: 8
position_endstop: 0
position_max: 180

[estop]
"""


def _joint_sections(ini: str) -> dict[int, dict[str, str]]:
    sections = {}
    for m in re.finditer(r"^\[JOINT_(\d+)\]\n(.*?)(?=^\[|\Z)", ini, re.M | re.S):
        sections[int(m.group(1))] = dict(re.findall(r"^(\w+) = (.*)$", m.group(2), re.M))
    return sections


@pytest.mark.parametrize("kinematics", ["cartesian", "corexy"])
def test_ini_joints_follow_the_hardware_json_numbers(tmp_path, kinematics):
    cfg = tmp_path / "machine.cfg"
    cfg.write_text(CFG.format(kinematics=kinematics), encoding="utf-8")
    graph = MachineConfigParser().parse(cfg)
    payload = json.loads(json.dumps(build_hardware_json(graph, "m8p")))
    number = {j["id"]: j["joint_number"] for j in payload["joints"]}
    assert (number["stepper_x"], number["stepper_y"], number["stepper_z"]) == (0, 1, 2)

    axes = AxisBuilder(graph, policy=AxisMappingPolicy.SPLIT_INTO_MULTIPLE_JOINTS).build()
    ini = render_ini_template("m8p", axes, payload.get("tools"), [], corexy=kinematics == "corexy")
    joints = _joint_sections(ini)
    # SCALE = microsteps * 200 / rotation_distance of the joint's own stepper
    assert float(joints[0]["SCALE"]) == 80.0          # stepper_x, 16 microsteps
    assert float(joints[1]["SCALE"]) == 40.0          # stepper_y, 8 microsteps
    assert abs(float(joints[2]["SCALE"])) == 200.0    # stepper_z
    assert float(joints[0]["MAX_LIMIT"]) == 200.0 and float(joints[1]["MAX_LIMIT"]) == 220.0


def test_a_custom_allocator_keeps_its_numbers(tmp_path):
    cfg = tmp_path / "machine.cfg"
    cfg.write_text(CFG.format(kinematics="cartesian"), encoding="utf-8")
    numbers = iter(range(10, 20))
    axes = AxisBuilder(MachineConfigParser().parse(cfg), policy=AxisMappingPolicy.SPLIT_INTO_MULTIPLE_JOINTS,
                       joint_number_allocator=lambda: next(numbers)).build()
    assert sorted(j.joint_number for a in axes for j in a.joints) == [10, 11, 12]
