"""[firmware_retraction] and [filament_change] / M600."""
from __future__ import annotations

from models.machineconfig.HardwareRecords import HardwareRecords

from pathlib import Path

import pytest

from MachineConfigParser import InvalidValueError, MachineConfigParser
from services.machineconfig import AxisBuilder, AxisMappingPolicy
from services.machineconfig.hardware_json_generator import build_hardware_json
from services.machinetemplates.ini_template_generator import render_ini_template
from services.machinetemplates.marlin_mcodes import M600_REMAP

PRINTER = open("tests/fixtures/profiles/full_klipper.cfg").read()
MILL = "[mcu]\nconnection: remora-spi\n\n[stepper_x]\nstep_pin: PF13\ndir_pin: PF12\nposition_endstop: 0\nposition_max: 200\n\n[estop]\n"
M_CODES = Path(__file__).resolve().parents[3] / "machine_config" / "m_codes"


def _payload(cfg):
    return build_hardware_json(MachineConfigParser().parse_string(cfg), "m")


def test_firmware_retraction_reaches_hardware_json():
    payload = _payload(PRINTER + "\n[firmware_retraction]\nretract_length: 0.8\nretract_speed: 35\n")
    assert payload["firmware_retraction"] == {
        "retract_length": 0.8, "retract_speed": 35.0, "unretract_extra_length": 0.0, "unretract_speed": 10.0,
    }
    assert "firmware_retraction" not in _payload(PRINTER) or _payload(PRINTER)["firmware_retraction"] is None


def test_filament_change_defaults_for_every_printer():
    change = _payload(PRINTER)["filament_change"]
    assert change["park_x"] == 0.0 and change["park_y"] == 0.0  # the X / Y minimum
    assert change["z_lift"] == 10.0 and change["unload_length"] == 50.0 and change["purge_length"] == 20.0
    custom = _payload(PRINTER + "\n[filament_change]\npark_x: 190\npark_y: 5\nunload_length: 80\n")["filament_change"]
    assert custom["park_x"] == 190.0 and custom["park_y"] == 5.0 and custom["unload_length"] == 80.0
    assert _payload(MILL).get("filament_change") is None


@pytest.mark.parametrize("bad", ["retract_length: -1", "retract_speed: fast"])
def test_bad_values(bad):
    with pytest.raises(InvalidValueError):
        MachineConfigParser().parse_string(PRINTER + f"\n[firmware_retraction]\n{bad}\n")


def test_ini_gets_the_m600_remap_and_its_values():
    graph = MachineConfigParser().parse_string(PRINTER)
    payload = build_hardware_json(graph, "m")
    axes = AxisBuilder(graph, policy=AxisMappingPolicy.SPLIT_INTO_MULTIPLE_JOINTS).build()
    ini = render_ini_template("m", axes, payload["tools"], remaps=[M600_REMAP],
                              filament_change=HardwareRecords.filament_change(payload))
    assert "REMAP=M600 modalgroup=10 ngc=m600" in ini
    section = ini.split("[FILAMENT_CHANGE]", 1)[1].split("\n\n", 1)[0]
    for key in ("PARK_X", "PARK_Y", "Z_LIFT", "UNLOAD_LENGTH", "UNLOAD_SPEED", "LOAD_LENGTH", "LOAD_SPEED",
                "PURGE_LENGTH", "PURGE_SPEED"):
        assert f"\n{key} = " in section, key


def test_m600_subroutine_reads_every_ini_value():
    ngc = (M_CODES / "m600.ngc").read_text()
    assert ngc.startswith("; m600.ngc") and "o<m600> sub" in ngc and "o<m600> endsub" in ngc
    for key in ("PARK_X", "PARK_Y", "Z_LIFT", "UNLOAD_LENGTH", "UNLOAD_SPEED", "LOAD_LENGTH", "LOAD_SPEED",
                "PURGE_LENGTH", "PURGE_SPEED"):
        assert f"#<_ini[FILAMENT_CHANGE]{key}>" in ngc, key
    assert "M0" in ngc and "G92 A#<a>" in ngc and "M70" in ngc and "M72" in ngc
