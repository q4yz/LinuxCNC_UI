"""calibration.ini: the file, the INI merge at machine start, the payload overlay."""
from __future__ import annotations

from core.calibration_file import (CalibrationFile, calibrated_ini, ini_overrides, merge_ini,
                                   overlay_payload)

INI = """[EMC]
MACHINE = test

[HAL]
HALFILE = machine.hal
HALFILE = webgui.hal

[HEATER_EXTRUDER]
PID_KP = 10
PID_KI = 1
# a comment
PID_KD = 50

[JOINT_2]
HOME = 5
HOME_OFFSET = 0
"""
PAYLOAD = {"probe": {"z_offset": 1.0}, "z_virtual_endstop": {"speed": 5},
           "axes": [{"id": "z", "joint_numbers": [2]}]}


def test_file_round_trip(tmp_path):
    f = CalibrationFile(tmp_path / "calibration.ini")
    assert f.load() == {}
    f.update({"HEATER_EXTRUDER": {"PID_KP": 12.5}, "CALIBRATION": {"PROBE_Z_OFFSET": 1.2}})
    f.set_state("pid_heater_extruder", last="2026-11-17T10:00:00", result="Kp 12.5")
    assert f.load()["HEATER_EXTRUDER"] == {"PID_KP": "12.5"}  # keys keep their case
    assert f.number("PROBE_Z_OFFSET") == 1.2
    assert f.state("pid_heater_extruder") == {"last": "2026-11-17T10:00:00", "result": "Kp 12.5"}
    f.set_state("pid_heater_extruder", result=None)
    assert f.state("pid_heater_extruder") == {"last": "2026-11-17T10:00:00"}
    assert (tmp_path / "calibration.ini").read_text().startswith("# Calibration results")


def test_merge_replaces_the_first_value_and_keeps_the_rest():
    merged = merge_ini(INI, {"HEATER_EXTRUDER": {"PID_KP": "12.5", "PID_KD": "60"},
                             "HAL": {"HALFILE": "other.hal"}, "INPUT_SHAPER": {"TYPE_X": "3"}})
    lines = merged.splitlines()
    assert "PID_KP = 12.5" in lines and "PID_KP = 10" not in lines
    assert "PID_KD = 60" in lines and "PID_KI = 1" in lines and "# a comment" in lines
    assert lines.count("HALFILE = webgui.hal") == 1 and "HALFILE = other.hal" in lines  # only the first
    assert "[INPUT_SHAPER]" in lines and "TYPE_X = 3" in lines
    assert not any("=" in l and "#" in l.split("=", 1)[1] for l in lines)  # no inline comments


def test_merge_adds_a_missing_key_to_its_section():
    merged = merge_ini(INI, {"EMC": {"DEBUG": "0"}})
    lines = merged.splitlines()
    assert lines.index("DEBUG = 0") < lines.index("[HAL]")


def test_probe_z_offset_moves_z_home_on_the_probe():
    overrides = ini_overrides({"CALIBRATION": {"PROBE_Z_OFFSET": "1.25"}}, PAYLOAD, INI)
    assert overrides["JOINT_2"] == {"HOME_OFFSET": "0.25", "HOME": "5.25"}
    no_virtual = dict(PAYLOAD, z_virtual_endstop=None)
    assert "JOINT_2" not in ini_overrides({"CALIBRATION": {"PROBE_Z_OFFSET": "1.25"}}, no_virtual, INI)
    # CALIBRATION sections never reach LinuxCNC
    assert ini_overrides({"CALIBRATION_STATE": {"a.last": "x"}}, PAYLOAD, INI) == {}


def test_calibrated_ini(tmp_path):
    ini = tmp_path / "machine.ini"
    ini.write_text(INI)
    assert calibrated_ini(ini, PAYLOAD) == (ini, [])
    CalibrationFile(tmp_path / "calibration.ini").update({"HEATER_EXTRUDER": {"PID_KP": 12.5}})
    path, keys = calibrated_ini(ini, PAYLOAD)
    assert path.name == "machine.calibrated.ini" and keys == ["HEATER_EXTRUDER.PID_KP"]
    assert "PID_KP = 12.5" in path.read_text() and ini.read_text() == INI
    CalibrationFile(tmp_path / "calibration.ini").update({"HEATER_EXTRUDER": {"PID_KP": None}})
    assert calibrated_ini(ini, PAYLOAD) == (ini, []) and not path.exists()


def test_overlay_payload():
    payload = {"probe": {"z_offset": 1.0}, "tools": [{"type": "extruder", "pressure_advance": 0.0}],
               "input_shaper": {"freq_x": 0.0, "type_x": "mzv"}}
    out = overlay_payload(payload, {"PROBE_Z_OFFSET": "1.3", "PRESSURE_ADVANCE": "0.05", "SHAPER_FREQ_X": "52.4",
                                    "SHAPER_TYPE_X": "ei", "SKEW_XY": "0.001"})
    assert out["probe"]["z_offset"] == 1.3 and out["tools"][0]["pressure_advance"] == 0.05
    assert out["input_shaper"]["freq_x"] == 52.4 and out["input_shaper"]["type_x"] == "ei"
    assert out["skew_correction"] == {"xy_factor": 0.001}
    assert payload["probe"]["z_offset"] == 1.0  # a copy
    assert "skew_correction" not in overlay_payload({}, {"SKEW_XY": "0.001"})  # no jointshape: nothing
