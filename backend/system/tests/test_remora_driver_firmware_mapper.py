"""RemoraDriverFirmwareMapper — TMC2209 UART tuning -> a `config.txt`
firmware module.

Shape verified against the real, working
`machine_config/example/ender3/config.txt`'s `driver_stepper_x` entry.
"""

from __future__ import annotations

from services.halcompiler.components.RemoraDriverFirmwareMapper import (
    RemoraDriverFirmwareMapper,
)

JOINT = {"id": "stepper_x", "joint_number": 0, "driver": "driver_stepper_x"}
DRIVER = {
    "id": "driver_stepper_x",
    "type": "TMC2209",
    "uart_pin": "mcu:PC6",
    "sense_resistor": 0.11,
    "run_current": 0.8,
    "microsteps": 16,
    "stealthchop_threshold": 200,
}


def test_a_tmc2209_driver_becomes_one_firmware_module():
    fragment = RemoraDriverFirmwareMapper.to_fragment([JOINT], {"driver_stepper_x": DRIVER})
    assert len(fragment.firmware_modules) == 1

    request = fragment.firmware_modules[0]
    assert request.mcu_id == "mcu"
    assert request.module == {
        "Name": "driver_stepper_x",
        "Thread": "On load",
        "Type": "TMC2209",
        "Comment": "stepper_x TMC driver",
        "RX pin": "PC_6",
        "RSense": 0.11,
        "Current": 800,
        "Microsteps": 16,
        "Stealth chop": "on",
        "Stall sensitivity": 0,
    }


def test_run_current_converts_amps_to_milliamps():
    """`run_current` is ingested in Klipper's native unit (amps); the
    reference config's `"Current"` is milliamps."""
    driver = dict(DRIVER, run_current=1.2)
    fragment = RemoraDriverFirmwareMapper.to_fragment([JOINT], {"driver_stepper_x": driver})
    assert fragment.firmware_modules[0].module["Current"] == 1200


def test_stealthchop_off_when_the_threshold_is_unset():
    driver = dict(DRIVER)
    del driver["stealthchop_threshold"]
    fragment = RemoraDriverFirmwareMapper.to_fragment([JOINT], {"driver_stepper_x": driver})
    assert fragment.firmware_modules[0].module["Stealth chop"] == "off"


def test_no_module_when_the_joint_has_no_driver_reference():
    joint = {"id": "stepper_x", "joint_number": 0}
    fragment = RemoraDriverFirmwareMapper.to_fragment([joint], {"driver_stepper_x": DRIVER})
    assert fragment.firmware_modules == []


def test_no_module_when_the_driver_has_no_uart_pin():
    driver = dict(DRIVER)
    del driver["uart_pin"]
    fragment = RemoraDriverFirmwareMapper.to_fragment([JOINT], {"driver_stepper_x": driver})
    assert fragment.firmware_modules == []


def test_no_module_for_a_non_tmc2209_driver():
    driver = dict(DRIVER, type="A4988")
    fragment = RemoraDriverFirmwareMapper.to_fragment([JOINT], {"driver_stepper_x": driver})
    assert fragment.firmware_modules == []


def test_no_module_when_the_referenced_driver_is_missing():
    """The validator's job to catch `E_UNKNOWN_REF` — the assembler
    trusts its input, but this mapper must not crash on a dangling
    reference either."""
    fragment = RemoraDriverFirmwareMapper.to_fragment([JOINT], {})
    assert fragment.firmware_modules == []


def test_missing_run_current_falls_back_to_the_documented_default():
    driver = dict(DRIVER)
    del driver["run_current"]
    fragment = RemoraDriverFirmwareMapper.to_fragment([JOINT], {"driver_stepper_x": driver})
    assert fragment.firmware_modules[0].module["Current"] == 800
