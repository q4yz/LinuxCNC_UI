"""The extruder joint's own limits and the pressure-advance wiring.

A joint 5 following error while printing (the extruder on an SB2209 CAN
node): the extruder joint planned with X / Y's 300 mm/s, while the node's
step generator stops at 20 kHz (28.3 mm/s at 705.5 steps/mm), pressure
advance came on top outside LinuxCNC's planner, and the extruder had a
positioning axis's 2 / 1 mm following-error allowance."""
from __future__ import annotations

import pytest

from MachineConfigParser import InvalidValueError, MachineConfigParser
from services.halcompiler import compile_machine_hal
from services.machineconfig import AxisBuilder, AxisMappingPolicy
from services.machineconfig.hardware_json_generator import build_hardware_json

PROFILE = open("tests/fixtures/profiles/corexy_can_extruder.cfg").read()


def _extruder_joint(cfg: str):
    axes = AxisBuilder(MachineConfigParser().parse_string(cfg), policy=AxisMappingPolicy.SPLIT_INTO_MULTIPLE_JOINTS).build()
    axis_a = next(a for a in axes if a.letter == "A")
    return axis_a, axis_a.joints[0]


def test_extruder_is_joint_5_on_the_node_capped_at_its_step_rate():
    axis_a, joint = _extruder_joint(PROFILE)
    assert joint.joint_number == 5
    steps_per_mm = 200 * 16 * 5 / 22.6789511
    assert joint.max_velocity == pytest.approx(0.9 * 20_000 / steps_per_mm)      # 25.5, not 300
    assert axis_a.max_velocity == joint.max_velocity
    # Klipper's default extrude-only accel: max_accel x 4 nozzle^2 / filament area
    ratio = 4 * 0.4 ** 2 / (3.14159265 * (1.75 / 2) ** 2)
    assert joint.max_acceleration == pytest.approx(3000 * ratio, rel=1e-6)
    assert joint.stepgen_maxaccel == pytest.approx(joint.max_acceleration * 1.1)
    assert (joint.ferror, joint.min_ferror) == (5.0, 2.0)


def test_declared_extrude_only_limits_win_below_the_cap():
    cfg = PROFILE.replace("[extruder]\n", "[extruder]\nmax_extrude_only_velocity: 20\nmax_extrude_only_accel: 500\n", 1)
    _, joint = _extruder_joint(cfg)
    assert (joint.max_velocity, joint.max_acceleration) == (20.0, 500.0)


def test_on_the_main_board_the_cap_is_its_base_thread():
    cfg = PROFILE.replace("sb2009:", "").replace("max_extrude", "#")
    _, joint = _extruder_joint(cfg)
    steps_per_mm = 200 * 16 * 5 / 22.6789511
    # remora-spi with PRU_base_freq 20000: the Klipper default (79.8 mm/s) is capped
    assert joint.max_velocity == pytest.approx(0.9 * 20_000 / steps_per_mm)


@pytest.mark.parametrize("bad", ["max_extrude_only_velocity: 0", "max_extrude_only_accel: -5"])
def test_extrude_only_limits_must_be_positive(bad):
    with pytest.raises(InvalidValueError):
        MachineConfigParser().parse_string(PROFILE.replace("[extruder]\n", f"[extruder]\n{bad}\n", 1))


def test_pressure_advance_gets_the_head_speed_and_the_limit():
    hal = compile_machine_hal(build_hardware_json(MachineConfigParser().parse_string(PROFILE), "m")).splitlines()
    comp = "extruder-heater_extruder"
    assert f"net heater_extruder-vel-x joint.0.vel-cmd => {comp}.vel-x" in hal
    assert f"net heater_extruder-vel-y joint.1.vel-cmd => {comp}.vel-y" in hal
    assert f"setp {comp}.max-velocity [JOINT_5]MAX_VELOCITY" in hal
