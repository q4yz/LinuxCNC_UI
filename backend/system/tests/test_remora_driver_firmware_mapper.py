"""RemoraDriverFirmwareMapper — TMC2209 UART tuning -> a `config.txt`
firmware module.

Shape verified against the real, working
`machine_config/example/ender3/config.txt`'s `driver_stepper_x` entry.
"""

from __future__ import annotations

import json

from MachineConfigParser import MachineConfigParser
from services.halcompiler.components.RemoraDriverFirmwareMapper import (
    RemoraDriverFirmwareMapper,
)
from services.machineconfig.hardware_json_generator import build_hardware_json

# as Klipper writes it: `microsteps` belongs to [stepper_x], the driver
# section has none
JOINT = {"id": "stepper_x", "joint_number": 0, "driver": "driver_stepper_x", "microsteps": 16}
DRIVER = {
    "id": "driver_stepper_x",
    "type": "TMC2209",
    "uart_pin": "mcu:PC6",
    "sense_resistor": 0.11,
    "run_current": 0.8,
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


def test_microsteps_come_from_the_stepper():
    """Klipper keeps `microsteps` in [stepper_z]; the driver used to get
    16 whatever the stepper said, while the axis scale used the
    stepper's value - a Z with 32 microsteps moved half the distance."""
    joint = dict(JOINT, microsteps=32)
    fragment = RemoraDriverFirmwareMapper.to_fragment([joint], {"driver_stepper_x": DRIVER})
    assert fragment.firmware_modules[0].module["Microsteps"] == 32


def test_the_stepper_value_wins_over_a_driver_section_value():
    """The scale is computed from the stepper, the driver must match it."""
    joint = dict(JOINT, microsteps=64)
    driver = dict(DRIVER, microsteps=16)
    fragment = RemoraDriverFirmwareMapper.to_fragment([joint], {"driver_stepper_x": driver})
    assert fragment.firmware_modules[0].module["Microsteps"] == 64


def test_microsteps_from_the_driver_section_or_the_default():
    joint = dict(JOINT)
    del joint["microsteps"]
    driver = dict(DRIVER, microsteps=8)
    fragment = RemoraDriverFirmwareMapper.to_fragment([joint], {"driver_stepper_x": driver})
    assert fragment.firmware_modules[0].module["Microsteps"] == 8
    fragment = RemoraDriverFirmwareMapper.to_fragment([joint], {"driver_stepper_x": DRIVER})
    assert fragment.firmware_modules[0].module["Microsteps"] == 16


def test_missing_sense_resistor_falls_back_to_the_default():
    driver = dict(DRIVER, sense_resistor=None)
    fragment = RemoraDriverFirmwareMapper.to_fragment([JOINT], {"driver_stepper_x": driver})
    assert fragment.firmware_modules[0].module["RSense"] == 0.11


CFG = """
[mcu]
connection: remora-spi
board: BTT MANTA M8P

[machine]
kinematics: cartesian
max_velocity: 300
max_accel: 3000

[stepper_x]
step_pin: PE2
dir_pin: PB4
enable_pin: !PC11
microsteps: 16
rotation_distance: 40
position_endstop: 0
position_max: 200

[tmc2209 stepper_x]
uart_pin: PC10
run_current: 0.8

[stepper_z]
step_pin: PD7
dir_pin: PD6
enable_pin: !PF10
microsteps: 32
rotation_distance: 8
position_endstop: 0
position_max: 200

[tmc2209 stepper_z]
uart_pin: PF9
run_current: 0.6
sense_resistor: 0.110

[estop]
"""


def test_profile_microsteps_reach_config_mcu(tmp_path):
    """End to end: [stepper_z] microsteps 32 -> the TMC2209 module of Z in config_mcu.txt."""
    cfg = tmp_path / "machine.cfg"
    cfg.write_text(CFG, encoding="utf-8")
    payload = json.loads(json.dumps(build_hardware_json(MachineConfigParser().parse(cfg), "m8p")))

    from services.halcompiler.HalAssembler import HalAssembler
    config = json.loads(HalAssembler(payload).assemble().files["config_mcu.txt"])
    tmc = {m["Name"]: m for m in config["Modules"] if m["Type"] == "TMC2209"}
    assert tmc["driver_stepper_x"]["Microsteps"] == 16
    assert tmc["driver_stepper_z"]["Microsteps"] == 32
    assert tmc["driver_stepper_z"]["Current"] == 600 and tmc["driver_stepper_z"]["RSense"] == 0.11
