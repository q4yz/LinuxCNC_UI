"""Sensorless homing: ``endstop_pin: tmc2209_stepper_x:virtual_endstop`` is
the driver's ``diag_pin``; ``driver_SGTHRS`` becomes the firmware module's
``Stall sensitivity`` with StealthChop on (StallGuard needs it)."""
from __future__ import annotations

import pytest

from MachineConfigParser import InvalidValueError, MachineConfigParser
from services.halcompiler.components.RemoraDriverFirmwareMapper import RemoraDriverFirmwareMapper
from services.machineconfig.hardware_json_generator import build_hardware_json

CFG = """
[mcu]
connection: remora-spi

[stepper_x]
step_pin: PF13
dir_pin: PF12
endstop_pin: tmc2209_stepper_x:virtual_endstop
position_endstop: 0
position_max: 250

[tmc2209 stepper_x]
uart_pin: PC4
run_current: 0.6
{tmc}

[stepper_y]
step_pin: PG0
dir_pin: PG1
endstop_pin: PG9
position_endstop: 0
position_max: 250

[stepper_z]
step_pin: PF11
dir_pin: PG3
endstop_pin: PG10
position_endstop: 0
position_max: 250

[estop]
"""


def _payload(tmc="diag_pin: ^PG6\ndriver_SGTHRS: 100"):
    return build_hardware_json(MachineConfigParser().parse_string(CFG.format(tmc=tmc)), "t")


def test_virtual_endstop_is_the_diag_pin_and_the_firmware_gets_sgthrs():
    payload = _payload()
    x = next(e for e in payload["endstops"] if "x" in str(e.get("id", "")))
    assert x["pin"] == "^PG6"
    driver = next(d for d in payload["drivers"] if d.get("uart_pin"))
    assert driver["diag_pin"] == "^PG6" and driver["stall_sensitivity"] == 100
    joints = [j for j in payload["joints"] if j.get("driver") == driver["id"]]
    module = RemoraDriverFirmwareMapper.to_fragment(joints, {driver["id"]: driver}).firmware_modules[0].module
    assert module["Stall sensitivity"] == 100 and module["Stealth chop"] == "on"


@pytest.mark.parametrize("tmc, missing", [("driver_SGTHRS: 100", "diag_pin"), ("diag_pin: ^PG6", "driver_SGTHRS")])
def test_virtual_endstop_needs_diag_pin_and_threshold(tmc, missing):
    with pytest.raises(InvalidValueError, match=missing):
        _payload(tmc)


def test_threshold_range():
    with pytest.raises(InvalidValueError, match="0 … 255"):
        _payload("diag_pin: ^PG6\ndriver_SGTHRS: 300")
