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


# -- input shaping / skew on CoreXY: the shapers before the mixing ----------- #

SHAPER = "\n[input_shaper]\nshaper_type: mzv\n\n[skew_correction]\n"


def _nets(text):
    return [line for line in text.splitlines() if line.startswith("net ")]


def _pins(text):
    """Every pin named in a ``net`` line (signal names and arrows dropped)."""
    out = []
    for line in _nets(text):
        out += [p for p in line.split()[2:] if p not in ("=>", "<=", "<=>")]
    return out


def test_corexy_gets_the_shapers_before_the_belt_mixing(tmp_path):
    payload = _payload(tmp_path, extra=SHAPER)
    assert not [d for d in validate_machine(payload) if d.is_error]
    text = compile_machine_hal(payload)
    nets = _nets(text)
    # joint -> shaper
    assert "net j0pos-cmd joint.0.motor-pos-cmd => shape-j0.pos-cmd-in" in nets
    assert "net j1pos-cmd joint.1.motor-pos-cmd => shape-j1.pos-cmd-in" in nets
    # shaped X / Y -> the mixing -> the motors (not straight to a stepgen)
    assert "net j0pos-cmd-shaped shape-j0.pos-cmd-out" in nets
    assert "net j0pos-cmd-shaped => corexy-a.in0 corexy-b.in0" in nets
    assert "net j1pos-cmd-shaped => corexy-a.in1 corexy-b.in1" in nets
    assert "net corexy-a-cmd corexy-a.out => remora.joint.0.pos-cmd" in nets
    # recovered X / Y -> the shaper's feedback -> the joint
    assert "net j0pos-fb corexy-x.out" in nets and "net j0pos-fb => shape-j0.pos-fb-in" in nets
    assert "net j0pos-fb-shaped shape-j0.pos-fb-out => joint.0.motor-pos-fb" in nets
    # skew: X gets x - factor * y, from the unshaped Y command
    assert "net j1pos-cmd => shape-j0.skew-ref" in nets
    # no shaper output straight to a motor, no joint fed twice
    assert not any("shape-j0.pos-cmd-out => remora" in n for n in nets)
    pins = _pins(text)
    assert len(pins) == len(set(pins)), "a pin is in two nets"


def test_one_servo_period_from_joint_to_motor(tmp_path):
    """remora.read -> X/Y feedback -> motion -> shapers -> A/B -> remora.write:
    the whole chain in one period (no last-period positions)."""
    text = compile_machine_hal(_payload(tmp_path, extra=SHAPER))
    addf = [line.split()[1] for line in text.splitlines() if line.startswith("addf ")]
    order = [addf.index(f) for f in ("remora.read", "corexy-x", "motion-controller", "shape-j0", "corexy-a",
                                     "remora.write")]
    assert order == sorted(order)
    assert addf.index("corexy-y") < addf.index("motion-controller")
    assert addf.index("shape-j1") < addf.index("corexy-b") < addf.index("remora.write")


def test_without_shaping_corexy_is_unchanged(tmp_path):
    nets = _nets(compile_machine_hal(_payload(tmp_path)))
    assert not any("shape-j" in n for n in nets)
    assert "net j0pos-cmd joint.0.motor-pos-cmd => corexy-a.in0 corexy-b.in0" in nets


def test_the_ui_wiring_reaches_the_corexy_shapers(tmp_path):
    from services.halcompiler import render_webgui_connections

    web = render_webgui_connections(_payload(tmp_path, extra=SHAPER))
    assert "net shaper-freq-x webgui.shaper-freq-x => shape-j0.shaper-freq" in web
    assert "net skew-xy webgui.skew-xy => shape-j0.skew-factor" in web
    assert "net resonance-amp-y webgui.resonance-amp-y => shape-j1.test-amp" in web
