"""[input_shaper], [skew_correction], [adxl345] -> the Remora jointshape
component on the X / Y joints."""
from __future__ import annotations

import pytest

from MachineConfigParser import InvalidValueError, MachineConfigParser
from services.halcompiler import compile_machine_hal, render_webgui_connections
from services.machineconfig.hardware_json_generator import build_hardware_json

PRINTER = open("tests/fixtures/profiles/full_klipper.cfg").read()
SHAPER = "\n[input_shaper]\nshaper_freq_x: 52.4\nshaper_freq_y: 41.8\nshaper_type_y: ei\n"


def _payload(extra=""):
    return build_hardware_json(MachineConfigParser().parse_string(PRINTER + extra), "m")


def test_config_reaches_hardware_json():
    payload = _payload(SHAPER + "\n[skew_correction]\nxy_ac: 142.0\nxy_bd: 140.8\nxy_ad: 100\n")
    assert payload["input_shaper"] == {"freq_x": 52.4, "freq_y": 41.8, "type_x": "mzv", "type_y": "ei",
                                       "damping_x": 0.1, "damping_y": 0.1}
    assert payload["skew_correction"]["xy_factor"] == pytest.approx(0.0084867, rel=1e-3)
    assert _payload("\n[skew_correction]\nxy_skew_factor: -0.002\n")["skew_correction"] == {"xy_factor": -0.002}


@pytest.mark.parametrize("bad", ["\n[input_shaper]\nshaper_type: smooth\n", "\n[input_shaper]\ndamping_ratio_x: 1.5\n",
                                 "\n[skew_correction]\nxy_ac: 140\n", "\n[adxl345]\naxes_map: x,x,z\n"])
def test_bad_values(bad):
    with pytest.raises(InvalidValueError):
        MachineConfigParser().parse_string(PRINTER + bad)


def test_jointshape_between_x_y_joints_and_their_stepgens():
    payload = _payload(SHAPER)
    hal = compile_machine_hal(payload).splitlines()
    x = next(a["joint_numbers"][0] for a in payload["axes"] if a["id"] == "x")
    y = next(a["joint_numbers"][0] for a in payload["axes"] if a["id"] == "y")
    assert f"loadrt jointshape names=shape-j{x},shape-j{y}" in hal
    assert f"net j{x}pos-cmd joint.{x}.motor-pos-cmd => shape-j{x}.pos-cmd-in" in hal
    assert f"net j{x}pos-cmd-shaped shape-j{x}.pos-cmd-out => remora.joint.{x}.pos-cmd" in hal
    assert f"net j{x}pos-fb-shaped shape-j{x}.pos-fb-out => joint.{x}.motor-pos-fb" in hal
    assert f"net j{x}pos-cmd joint.{x}.motor-pos-cmd => remora.joint.{x}.pos-cmd" not in hal
    assert f"net j{y}pos-cmd => shape-j{x}.skew-ref" in hal
    assert f"setp shape-j{x}.shaper-type [INPUT_SHAPER]TYPE_X" in hal
    assert f"setp shape-j{y}.shaper-type [INPUT_SHAPER]TYPE_Y" in hal
    from services.halcompiler.components.JointShapeHalMapper import JointShapeHalMapper
    from services.machinetemplates.ini_template_generator import render_ini_template

    types = JointShapeHalMapper.ini_shaper_types(payload)
    assert types == {"x": 2, "y": 4}
    ini = render_ini_template("m", [], [], shaper_types=types).splitlines()
    assert "[INPUT_SHAPER]" in ini and "TYPE_X = 2" in ini and "TYPE_Y = 4" in ini
    z = next(a["joint_numbers"][0] for a in payload["axes"] if a["id"] == "z")
    assert f"net j{z}pos-cmd joint.{z}.motor-pos-cmd => remora.joint.{z}.pos-cmd" in hal  # Z untouched
    webgui = render_webgui_connections(payload).splitlines()
    assert f"net shaper-freq-x webgui.shaper-freq-x => shape-j{x}.shaper-freq" in webgui
    assert f"net skew-xy webgui.skew-xy => shape-j{x}.skew-factor" in webgui
    assert f"net resonance-amp-y webgui.resonance-amp-y => shape-j{y}.test-amp" in webgui
    assert f"net resonance-freq webgui.resonance-freq => shape-j{x}.test-freq shape-j{y}.test-freq" in webgui


def test_shapers_run_before_the_board_write():
    """Tied in one tier, remora.write ran first and the board got last
    period's shaped position; the write is now last."""
    payload = _payload(SHAPER)
    addf = [line.split()[1] for line in compile_machine_hal(payload).splitlines() if line.startswith("addf ")]
    x = next(a["joint_numbers"][0] for a in payload["axes"] if a["id"] == "x")
    assert addf.index("motion-controller") < addf.index(f"shape-j{x}") < addf.index("remora.write")
    assert addf[-1] in ("remora.write", "remora.update-freq") or addf.index("remora.write") > max(
        i for i, f in enumerate(addf) if f.startswith(("shape-j", "extruder-")))


def test_nothing_without_the_sections():
    payload = _payload()
    assert "jointshape" not in compile_machine_hal(payload)
    assert "shaper-freq" not in render_webgui_connections(payload)


def test_adxl345_section_alone_loads_the_test_signal():
    payload = _payload("\n[adxl345]\nspi_device: /dev/spidev1.1\naxes_map: -y,x,z\n")
    assert payload["adxl345"]["axes_map"] == "-y,x,z"
    assert "loadrt jointshape" in compile_machine_hal(payload)
