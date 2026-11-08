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
from services.machinetemplates.marlin_mcodes import marlin_remaps

PRINTER = open("tests/fixtures/profiles/full_klipper.cfg").read()
M_CODES = Path(__file__).resolve().parents[3] / "machine_config" / "m_codes"
MILL = "[mcu]\nconnection: remora-spi\n\n[stepper_x]\nstep_pin: PF13\ndir_pin: PF12\nposition_endstop: 0\nposition_max: 200\n\n[estop]\n"


def _payload(cfg=PRINTER):
    return build_hardware_json(MachineConfigParser().parse_string(cfg), "m")


def test_remaps_for_a_printer():
    assert marlin_remaps(_payload()) == [
        "REMAP=M104 modalgroup=10 argspec=pq ngc=m104",
        "REMAP=M109 modalgroup=10 argspec=pq ngc=m109",
        "REMAP=M140 modalgroup=10 argspec=p ngc=m140",
        "REMAP=M190 modalgroup=10 argspec=p ngc=m190",
        "REMAP=M106 modalgroup=10 argspec=pq ngc=m106",
        "REMAP=M107 modalgroup=10 argspec=q ngc=m107",
    ]


def test_none_for_a_mill():
    assert marlin_remaps(_payload(MILL)) == []


def test_shared_files_exist():
    for name in ("m104.ngc", "m109.ngc", "m140.ngc", "m190.ngc", "m106.ngc", "m107.ngc", "g28.ngc"):
        assert (M_CODES / name).is_file(), name
    for name in ("M180", "M181", "M182", "M183"):
        helper = M_CODES / name
        assert helper.is_file() and os.access(helper, os.X_OK), name
    assert "M181 P#<temp> Q-1" in (M_CODES / "m190.ngc").read_text()
    assert "#<_ini[UI_HOME]X>" in (M_CODES / "g28.ngc").read_text()


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
