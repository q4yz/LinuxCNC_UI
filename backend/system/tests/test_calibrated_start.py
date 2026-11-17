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
