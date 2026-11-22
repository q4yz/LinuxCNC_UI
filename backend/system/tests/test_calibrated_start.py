"""Machine start: calibration.ini merged into machine.calibrated.ini."""
from __future__ import annotations

import json

from services.MachineLifecycleService import MachineLifecycleService


def test_starts_the_calibrated_ini(tmp_path):
    ini = tmp_path / "machine.ini"
    ini.write_text("[HEATER_BED]\nPID_KP = 10\n")
    (tmp_path / "hardware.json").write_text(json.dumps({}))
    assert MachineLifecycleService._calibrated(ini) == ini
    (tmp_path / "calibration.ini").write_text("[HEATER_BED]\nPID_KP = 22\n")
    path = MachineLifecycleService._calibrated(ini)
    assert path.name == "machine.calibrated.ini" and "PID_KP = 22" in path.read_text()


def test_a_broken_calibration_file_never_stops_the_machine(tmp_path):
    ini = tmp_path / "machine.ini"
    ini.write_text("[HEATER_BED]\nPID_KP = 10\n")
    (tmp_path / "calibration.ini").write_bytes(b"\xff\xfe garbage [[[")
    assert MachineLifecycleService._calibrated(ini) == ini


def test_start_puts_the_stallguard_threshold_into_the_board(tmp_path):
    from core.calibration_file import CalibrationFile

    ini = tmp_path / "machine.ini"
    ini.write_text("[EMC]\nMACHINE = m\n")
    board = {"Modules": [{"Type": "TMC2209", "Comment": "stepper_x TMC driver", "Stall sensitivity": 100,
                          "Stealth chop": "on"}]}
    (tmp_path / "config_mcu.txt").write_text(json.dumps(board, indent=2))
    (tmp_path / "calibration.ini").write_text("[CALIBRATION]\nSTALL_STEPPER_X = 70\n")
    assert MachineLifecycleService._calibrated(ini) == ini  # no INI keys
    assert json.loads((tmp_path / "config_mcu.txt").read_text())["Modules"][0]["Stall sensitivity"] == 70
    assert CalibrationFile(tmp_path / "calibration.ini").state("sensorless_stepper_x") == {"loaded": "70"}
