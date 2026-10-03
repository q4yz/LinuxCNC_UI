"""hardware.json axes carry the same velocity/acceleration limits that
machine.ini's ``[AXIS_*] MAX_VELOCITY``/``MAX_ACCELERATION`` get.

Both come from one ``AxisBuilder`` run, so the UI's slider limits and
LinuxCNC's own limits can never drift apart.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from MachineConfigParser import MachineConfigParser
from models.machineconfig.HardwareJsonModels import HardwareJson
from services.machineconfig.AxisBuilder import AxisBuilder
from services.machineconfig.hardware_json_generator import build_hardware_json

PROFILE_DIR = Path(__file__).resolve().parents[3] / "machine_config" / "profiles"


@pytest.mark.parametrize("profile_name", ["printnc.cfg", "mcu_remora_spi.cfg"])
def test_axis_limits_match_the_ini_axis_builder(profile_name):
    profile = PROFILE_DIR / profile_name
    if not profile.exists():
        pytest.skip(f"{profile_name} not present")
    graph = MachineConfigParser().parse(profile)
    payload = build_hardware_json(graph, profile.stem)
    HardwareJson.model_validate(payload)

    ini_axes = {a.letter.lower(): a for a in AxisBuilder(graph).build()}
    for axis in payload["axes"]:
        ini = ini_axes[axis["id"]]
        if ini.max_velocity > 0:
            assert axis["max_velocity"] == ini.max_velocity
            assert axis["max_acceleration"] == ini.max_acceleration
        else:
            # A 0 limit (the synthesised extruder axis) means "not set" —
            # never shipped as a real limit the UI would size from.
            assert axis.get("max_velocity") is None


def test_printnc_z_gets_its_own_slower_limit():
    profile = PROFILE_DIR / "printnc.cfg"
    if not profile.exists():
        pytest.skip("printnc.cfg not present")
    payload = build_hardware_json(MachineConfigParser().parse(profile), profile.stem)
    by_id = {a["id"]: a for a in payload["axes"]}
    assert (by_id["x"]["max_velocity"], by_id["x"]["max_acceleration"]) == (70.0, 400.0)
    assert by_id["z"]["max_velocity"] == 50.0
