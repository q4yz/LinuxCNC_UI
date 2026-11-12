"""Marlin heater / fan M-codes: this machine's REMAP lines, and the
shared files in ``machine_config/m_codes/`` they rely on."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from MachineConfigParser import MachineConfigParser
from services.machineconfig.hardware_json_generator import build_hardware_json
from services.machinetemplates.marlin_mcodes import MARLIN_USER_MCODES, USER_MCODE_REMAP

PRINTER = open("tests/fixtures/profiles/full_klipper.cfg").read()
M_CODES = Path(__file__).resolve().parents[3] / "machine_config" / "m_codes"
MILL = "[mcu]\nconnection: remora-spi\n\n[stepper_x]\nstep_pin: PF13\ndir_pin: PF12\nposition_endstop: 0\nposition_max: 200\n\n[estop]\n"


def _payload(cfg=PRINTER):
    return build_hardware_json(MachineConfigParser().parse_string(cfg), "m")


def test_marlin_codes_are_executable_user_mcodes():
    """LinuxCNC 2.9 cannot REMAP M100-M199: each Marlin code is a user
    M-code program, a copy of the helper script."""
    helper = (M_CODES / "M180").read_bytes()
    for name in (*MARLIN_USER_MCODES, "M180", "M181", "M182", "M183"):
        path = M_CODES / name
        assert path.is_file() and os.access(path, os.X_OK), name
        assert path.read_bytes() == helper, f"{name} is not the same script as M180"
    for gone in ("m104.ngc", "m106.ngc", "m107.ngc", "m109.ngc", "m140.ngc", "m190.ngc"):
        assert not (M_CODES / gone).exists(), gone
    assert "#<_ini[UI_HOME]X>" in (M_CODES / "g28.ngc").read_text()


def test_no_ini_remap_in_the_user_mcode_range():
    from services.machineconfig import AxisBuilder, AxisMappingPolicy
    from services.machinetemplates.ini_template_generator import render_ini_template

    axes = AxisBuilder(MachineConfigParser().parse_string(PRINTER), policy=AxisMappingPolicy.SPLIT_INTO_MULTIPLE_JOINTS).build()
    ini = render_ini_template("m", axes)
    assert not [line for line in ini.splitlines() if USER_MCODE_REMAP.match(line)]
    try:
        render_ini_template("m", axes, remaps=["REMAP=M106 modalgroup=10 argspec=pq ngc=m106"])
    except ValueError as exc:
        assert "M100-M199" in str(exc)
    else:
        raise AssertionError("a REMAP=M106 was written")


def _run_helper(tmp_path, name, *args, payload=None):
    """Run a helper against a fake machine backend that records requests."""
    payload = payload or _payload()
    (tmp_path / "hardware.json").write_text(json.dumps(payload))
    (tmp_path / "machine.ini").write_text("")
    script = f"""
import json, runpy, sys, urllib.request
calls = []
class Resp:
    def read(self): return b""
    def __enter__(self): return self
    def __exit__(self, *a): return False
def urlopen(req, timeout=0):
    calls.append([req.get_method(), req.full_url, json.loads(req.data)])
    return Resp()
urllib.request.urlopen = urlopen
sys.argv = [{str(M_CODES / name)!r}, *{list(args)!r}]
try:
    runpy.run_path(sys.argv[0], run_name="__main__")
except SystemExit as exc:
    print(json.dumps({{"code": exc.code, "calls": calls}}))
"""
    env = {**os.environ, "INI_FILE_NAME": str(tmp_path / "machine.ini")}
    out = subprocess.run([sys.executable, "-I", "-c", script], capture_output=True, text=True, env=env, cwd=tmp_path)
    return json.loads(out.stdout.strip().splitlines()[-1]), out.stderr


def test_helper_sets_a_heater_target(tmp_path):
    result, _ = _run_helper(tmp_path, "M180", "215", "0")
    assert result == {"code": 0, "calls": [
        ["POST", "http://127.0.0.1:8000/api/v1/modules/tools/tools/heater_extruder/target",
         {"id": "heater_extruder", "target": 215.0}]]}
    result, _ = _run_helper(tmp_path, "M180", "60", "-1")
    assert result["calls"][0][1].endswith("/tools/heater_bed/target")


def test_helper_drives_the_part_fan_not_the_heater_placeholder(tmp_path):
    result, _ = _run_helper(tmp_path, "M182", "255", "0")
    assert result["calls"] == [["PUT", "http://127.0.0.1:8000/api/v1/modules/io/fan", {"value": 100.0}]]
    result, err = _run_helper(tmp_path, "M182", "255", "1")
    assert result["code"] == 1 and "no part fan 1" in err


def test_helper_unknown_heater(tmp_path):
    result, err = _run_helper(tmp_path, "M180", "200", "3")
    assert result["code"] == 1 and "no extruder 3" in err


def test_helper_sets_an_led(tmp_path):
    cfg = PRINTER + "\n[neopixel sb]\npin: PD3\nchain_count: 3\nsegments: 1, 2-3\n"
    payload = build_hardware_json(MachineConfigParser().parse_string(cfg), "m")
    (tmp_path / "hardware.json").write_text(json.dumps(payload))
    (tmp_path / "machine.ini").write_text("")
    result, _ = _run_helper(tmp_path, "M183", str(0xFF8000), "2", payload=payload)
    assert result["calls"] == [["PUT", "http://127.0.0.1:8000/api/v1/leds/sb",
                                {"red": 1.0, "green": 128 / 255, "blue": 0.0, "index": 2}]]


def test_marlin_names_map_onto_the_helper_actions(tmp_path):
    """LinuxCNC passes -1 for a P / Q the line did not give."""
    target = "http://127.0.0.1:8000/api/v1/modules/tools/tools/heater_{}/target"
    fan = "http://127.0.0.1:8000/api/v1/modules/io/fan"
    cases = [
        ("M104", ["215", "-1"], ["POST", target.format("extruder"), {"id": "heater_extruder", "target": 215.0}]),
        ("M104", ["215", "0"], ["POST", target.format("extruder"), {"id": "heater_extruder", "target": 215.0}]),
        ("M140", ["60", "-1"], ["POST", target.format("bed"), {"id": "heater_bed", "target": 60.0}]),
        ("M140", ["60", "0"], ["POST", target.format("bed"), {"id": "heater_bed", "target": 60.0}]),
        ("M109", ["0", "-1"], ["POST", target.format("extruder"), {"id": "heater_extruder", "target": 0.0}]),
        ("M190", ["0", "-1"], ["POST", target.format("bed"), {"id": "heater_bed", "target": 0.0}]),
        ("M106", ["128", "-1"], ["PUT", fan, {"value": 128 / 255 * 100.0}]),
        ("M106", ["-1", "-1"], ["PUT", fan, {"value": 100.0}]),  # Marlin: no S = full
        ("M107", ["-1", "-1"], ["PUT", fan, {"value": 0.0}]),
    ]
    for name, args, call in cases:
        result, err = _run_helper(tmp_path, name, *args)
        assert result == {"code": 0, "calls": [call]}, (name, args, err)


def test_marlin_heater_code_needs_a_temperature(tmp_path):
    result, err = _run_helper(tmp_path, "M104", "-1", "-1")
    assert result["code"] == 1 and "needs P" in err
