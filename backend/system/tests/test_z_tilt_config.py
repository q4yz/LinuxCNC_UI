"""``[z_tilt]``: ``.cfg`` -> hardware.json, the per-motor offsets in
machine.hal and their targets in webgui_connections.hal
(`.agent/component/z_tilt.md`)."""
from __future__ import annotations

import pytest

from MachineConfigParser import InvalidValueError, MachineConfigParser, MissingRequiredKeywordError
from services.halcompiler import compile_machine_hal, render_webgui_connections
from services.machineconfig.hardware_json_generator import build_hardware_json

CFG = """
[mcu]
connection: remora-spi

[stepper_x]
step_pin: PF13
dir_pin: PF12
position_endstop: 0
position_max: 200

[stepper_y]
step_pin: PG0
dir_pin: PG1
position_endstop: 0
position_max: 200

[stepper_z]
step_pin: PF11
dir_pin: PG3
position_endstop: 0
position_min: -2
position_max: 100

[stepper_z1]
step_pin: PG4
dir_pin: PC1
position_endstop: 0
position_max: 100
{z2}
[estop]

[probe]
pin: PB7

[z_tilt]
z_positions:
{positions}
points:
{points}
retries: 4
retry_tolerance: 0.01
"""

Z2 = """
[stepper_z2]
step_pin: PF9
dir_pin: PF10
position_endstop: 0
position_max: 100
"""
TWO = "    -50, 100\n    260, 100"
THREE = "    -50, 18\n    260, 18\n    100, 250"
LINE = "    20, 100\n    180, 100"
SPREAD = "    30, 5\n    230, 5\n    100, 200"


def _payload(positions=TWO, points=LINE, z2="", extra=""):
    src = CFG.format(positions=positions, points=points, z2=z2) + extra
    return build_hardware_json(MachineConfigParser().parse_string(src), "m")


def test_reaches_hardware_json():
    assert _payload()["z_tilt"] == {
        "z_positions": [[-50.0, 100.0], [260.0, 100.0]],
        "points": [[20.0, 100.0], [180.0, 100.0]],
        "joints": [2, 3],
        "speed": 50.0, "horizontal_move_z": 5.0, "probe_speed": 5.0, "probe_min_z": -2.0,
        "retries": 4, "retry_tolerance": 0.01, "max_adjust": 5.0,
    }


def test_offsets_spliced_into_the_z_joints():
    payload = _payload()
    hal = compile_machine_hal(payload)
    for k, joint in enumerate((2, 3)):
        assert f"net j{joint}pos-cmd joint.{joint}.motor-pos-cmd => ztilt-{k}.in" in hal
        assert f"net j{joint}pos-cmd-tilt ztilt-{k}.out => remora.joint.{joint}.pos-cmd" in hal
        assert f"net j{joint}pos-fb-raw remora.joint.{joint}.pos-fb => ztilt-{k}.fb-in" in hal
        assert f"net j{joint}pos-fb ztilt-{k}.fb-out => joint.{joint}.motor-pos-fb" in hal
        assert f"net ztilt-{k}-offset ztilt-ramp-{k}.out => ztilt-{k}.offset" in hal
        assert f"setp ztilt-ramp-{k}.max 5" in hal
    # X and Y untouched.
    assert "net j0pos-cmd joint.0.motor-pos-cmd => remora.joint.0.pos-cmd" in hal
    addf = [line.split()[1] for line in hal.splitlines() if line.startswith("addf")]
    assert addf.index("remora.read") < addf.index("ztilt-0.update-feedback") < addf.index("motion-controller")
    assert addf.index("motion-controller") < addf.index("ztilt-0.update-output") < addf.index("remora.write")
    assert addf.index("ztilt-ramp-0") < addf.index("ztilt-0.update-output")
    lines = render_webgui_connections(payload).splitlines()
    assert "net ztilt-0-target webgui.ztilt-0 => ztilt-ramp-0.in" in lines
    assert "net ztilt-1-target webgui.ztilt-1 => ztilt-ramp-1.in" in lines


def test_three_motors():
    payload = _payload(THREE, SPREAD, Z2)
    assert payload["z_tilt"]["joints"] == [2, 3, 4]
    assert "loadrt offset names=ztilt-0,ztilt-1,ztilt-2" in compile_machine_hal(payload)


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        (dict(positions=THREE), InvalidValueError),                     # 3 pivots, 2 motors
        (dict(positions=THREE, points=LINE, z2=Z2), InvalidValueError),  # plane, points on a line
        (dict(points="    20, 100"), InvalidValueError),                  # one point
        (dict(points="    20; 100\n    30, 5"), InvalidValueError),       # not "X, Y"
        (dict(extra="speed: 0\n"), InvalidValueError),
        (dict(extra="max_adjust: -1\n"), InvalidValueError),
    ],
)
def test_errors(kwargs, error):
    with pytest.raises(error):
        _payload(**kwargs)


def test_needs_a_probe():
    src = CFG.format(positions=TWO, points=LINE, z2="").replace("[probe]\npin: PB7\n", "")
    with pytest.raises(InvalidValueError, match="probe"):
        build_hardware_json(MachineConfigParser().parse_string(src), "m")


def test_needs_two_z_motors():
    src = CFG.format(positions=TWO, points=LINE, z2="").replace(
        "[stepper_z1]\nstep_pin: PG4\ndir_pin: PC1\nposition_endstop: 0\nposition_max: 100\n", "")
    with pytest.raises(InvalidValueError, match="two or more motors"):
        build_hardware_json(MachineConfigParser().parse_string(src), "m")


def test_missing_points():
    src = CFG.format(positions=TWO, points="", z2="").replace("points:\n\n", "")
    with pytest.raises(MissingRequiredKeywordError):
        build_hardware_json(MachineConfigParser().parse_string(src), "m")
