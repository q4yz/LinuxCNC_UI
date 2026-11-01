"""``kinematics: corexy`` end to end: still ``trivkins`` in LinuxCNC, the
belt math (A = X + Y, B = X - Y and back) in HAL between the joints and
the Remora step generators (`.agent/component/corexy.md`)."""
from __future__ import annotations

import json
import re

import pytest

from MachineConfigParser import MachineConfigParser
from services.halcompiler import compile_machine_hal, validate_machine
from services.machineconfig import AxisBuilder, AxisMappingPolicy
from services.machineconfig.hardware_json_generator import build_hardware_json
from services.machinetemplates.ini_template_generator import render_ini_template

CFG = """
[mcu]
connection: {connection}

[machine]
kinematics: corexy
max_velocity: 300
max_accel: 3000

[stepper_x]
step_pin: {pin}13
dir_pin: {pin}12
position_endstop: 0
position_max: 200
endstop_pin: PG6

[stepper_y]
step_pin: {pin}11
dir_pin: {pin}10
position_endstop: 0
position_max: 200
endstop_pin: PG9

[stepper_z]
step_pin: {pin}9
dir_pin: {pin}8
position_endstop: 0
position_max: 100

[estop]
{extra}
"""


def _graph(tmp_path, connection="remora-spi", extra=""):
    pin = "PF" if connection == "remora-spi" else "pin_"
    cfg = tmp_path / "machine.cfg"
    cfg.write_text(CFG.format(connection=connection, pin=pin, extra=extra), encoding="utf-8")
    return MachineConfigParser().parse(cfg)


def _payload(tmp_path, **kwargs):
    return json.loads(json.dumps(build_hardware_json(_graph(tmp_path, **kwargs), "corexy")))


def test_the_belt_math_sits_between_the_joints_and_remora(tmp_path):
    payload = _payload(tmp_path)
    assert payload["kinematics"] == "corexy"
    assert not [d for d in validate_machine(payload) if d.is_error]
    text = compile_machine_hal(payload)

    # A = X + Y, B = X - Y  (motor A = remora joint 0 = [stepper_x])
    assert "net j0pos-cmd joint.0.motor-pos-cmd => corexy-a.in0 corexy-b.in0" in text
    assert "net j1pos-cmd joint.1.motor-pos-cmd => corexy-a.in1 corexy-b.in1" in text
    assert "setp corexy-b.gain1 -1" in text
    assert "net corexy-a-cmd corexy-a.out => remora.joint.0.pos-cmd" in text
    assert "net corexy-b-cmd corexy-b.out => remora.joint.1.pos-cmd" in text
    # X = (A + B) / 2, Y = (A - B) / 2
    assert "setp corexy-y.gain1 -0.5" in text
    assert "net j0pos-fb corexy-x.out => joint.0.motor-pos-fb" in text
    assert "net j1pos-fb corexy-y.out => joint.1.motor-pos-fb" in text
    # No direct X / Y position nets (they would be second writers); Z stays direct.
    assert "remora.joint.0.pos-fb => joint.0.motor-pos-fb" not in text
    assert "net j2pos-cmd joint.2.motor-pos-cmd => remora.joint.2.pos-cmd" in text
    # Homing stays per axis, enables unchanged.
    assert "net endstop_x_min-sw => joint.0.home-sw-in" in text
    assert "net endstop_y_min-sw => joint.1.home-sw-in" in text
    assert "net j0enable joint.0.amp-enable-out => remora.joint.0.enable" in text


def test_the_sums_run_after_motion_and_before_remora_write(tmp_path):
    text = compile_machine_hal(_payload(tmp_path))
    addf = [line.split()[1] for line in text.splitlines() if line.startswith("addf ")]
    assert addf.index("motion-controller") < addf.index("corexy-a") < addf.index("remora.write")


def test_the_ini_stays_trivkins_and_doubles_the_motor_acceleration(tmp_path):
    graph = _graph(tmp_path)
    axes = AxisBuilder(graph, policy=AxisMappingPolicy.SPLIT_INTO_MULTIPLE_JOINTS).build()
    plain = render_ini_template("m", axes)
    corexy = render_ini_template("m", axes, corexy=True)
    assert "KINEMATICS = trivkins" in corexy

    def accel(text, n):
        section = text.split(f"[JOINT_{n}]")[1]
        return float(re.search(r"STEPGEN_MAXACCEL = ([\d.]+)", section).group(1))

    assert accel(corexy, 0) == 2 * accel(plain, 0)  # X: motor sees ax + ay
    assert accel(corexy, 1) == 2 * accel(plain, 1)
    assert accel(corexy, 2) == accel(plain, 2)      # Z unchanged


def test_corexy_needs_a_remora_board(tmp_path):
    payload = _payload(tmp_path, connection="parallelport")
    assert "E_COREXY" in {d.code for d in validate_machine(payload)}


def test_corexy_needs_one_joint_on_x_and_y(tmp_path):
    payload = _payload(tmp_path, extra="[stepper_y1]\nstep_pin: PF7\ndir_pin: PF6\nposition_max: 200\n")
    assert any(d.code == "E_COREXY" and d.where == "y" for d in validate_machine(payload))


def test_cartesian_is_unchanged(tmp_path):
    cfg = (tmp_path / "c.cfg")
    cfg.write_text(CFG.format(connection="remora-spi", pin="PF", extra="").replace("corexy", "cartesian"),
                   encoding="utf-8")
    text = compile_machine_hal(json.loads(json.dumps(build_hardware_json(MachineConfigParser().parse(cfg), "c"))))
    assert "corexy" not in text
    assert "net j0pos-cmd joint.0.motor-pos-cmd => remora.joint.0.pos-cmd" in text
