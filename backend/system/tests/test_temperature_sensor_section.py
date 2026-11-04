"""``[temperature_sensor NAME]`` end to end: ``.cfg`` -> ``hardware.json`` ->
machine.hal, config.txt and webgui_connections.hal
(`.agent/component/temperature_sensor.md`)."""
from __future__ import annotations

import json

import pytest

from MachineConfigParser import (
    DuplicateTemperatureSensorError,
    InvalidValueError,
    MachineConfigParser,
    MissingRequiredKeywordError,
    UndefinedMcuError,
    UnsupportedSectionError,
)
from services.halcompiler import compile_machine_hal, render_webgui_connections, validate_machine
from services.halcompiler.HalAssembler import HalAssembler

CFG = """
[mcu]
connection: remora-spi

[stepper_x]
step_pin: PF13
dir_pin: PF12
position_endstop: 0
position_max: 200

[estop]

[heater_bed]
heater_pin: PA1
sensor_type: Generic 3950
sensor_pin: PF3
control: watermark
min_temp: 0
max_temp: 120

[temperature_sensor chamber]
sensor_type: Generic 3950
sensor_pin: PF5

[temperature_sensor host]
sensor_type: hal
sensor_pin: rpi-monitor.cpu-temp

[temperature_sensor board]
sensor_type: HAL
sensor_pin: cpu-temp
{extra}
"""


def _payload(tmp_path, extra=""):
    cfg = tmp_path / "machine.cfg"
    cfg.write_text(CFG.format(extra=extra), encoding="utf-8")
    from services.machineconfig.hardware_json_generator import build_hardware_json
    return json.loads(json.dumps(build_hardware_json(MachineConfigParser().parse(cfg), "sensors")))


def test_sections_reach_hardware_json(tmp_path):
    sensors = _payload(tmp_path)["temperature_sensors"]
    assert sensors == [
        {"id": "bed", "pin": "PF3", "type": "Generic 3950"},
        {"id": "chamber", "pin": "PF5", "type": "Generic 3950"},
        {"id": "host", "pin": "rpi-monitor.cpu-temp", "type": "hal"},
        {"id": "board", "pin": "cpu-temp", "type": "hal"},
    ]


def test_validates_clean(tmp_path):
    errors = [d for d in validate_machine(_payload(tmp_path)) if d.is_error]
    assert errors == []


def test_machine_hal_wiring(tmp_path):
    hal = compile_machine_hal(_payload(tmp_path))
    assert "net chamber-PV <= remora.PV.1" in hal
    assert "net host-PV <= rpi-monitor.cpu-temp" in hal
    # A HAL signal is the operator's own — machine.hal leaves it alone.
    assert "cpu-temp" not in hal.replace("rpi-monitor.cpu-temp", "")
    # The component behind a HAL pin is never loaded by the generator.
    assert "rpi-monitor " not in hal and "loadusr -Wn rpi-monitor" not in hal


def test_board_thermistor_gets_firmware_module(tmp_path):
    fragment = HalAssembler(_payload(tmp_path)).assemble()
    config = json.loads(fragment.files["config_mcu.txt"])
    modules = {m["Comment"]: m for m in config["Modules"] if m.get("Type") == "Temperature"}
    assert set(modules) == {"bed", "chamber"}
    assert modules["chamber"]["PV[i]"] == 1
    assert modules["chamber"]["Thermistor"]["Pin"] == "PF_5"


def test_webgui_bindings_reach_the_plot(tmp_path):
    lines = render_webgui_connections(_payload(tmp_path)).splitlines()
    assert "net bed-PV => webgui.bed" in lines
    assert "net chamber-PV => webgui.chamber" in lines
    assert "net host-PV => webgui.host" in lines
    assert "net cpu-temp => webgui.board" in lines
    # The heater's own sensor is bound once, by the heater.
    assert lines.count("net bed-PV => webgui.bed") == 1


def test_missing_keys(tmp_path):
    with pytest.raises(MissingRequiredKeywordError):
        _payload(tmp_path, "[temperature_sensor x]\nsensor_type: hal\n")
    with pytest.raises(MissingRequiredKeywordError):
        _payload(tmp_path, "[temperature_sensor x]\nsensor_pin: PF6\n")


def test_bad_hal_name(tmp_path):
    with pytest.raises(InvalidValueError):
        _payload(tmp_path, "[temperature_sensor x]\nsensor_type: hal\nsensor_pin: a b\n")


def test_unknown_mcu_on_board_pin(tmp_path):
    with pytest.raises(UndefinedMcuError):
        _payload(tmp_path, "[temperature_sensor x]\nsensor_type: Generic 3950\nsensor_pin: ebb:PA3\n")


def test_hal_pin_is_not_checked_as_board_pin(tmp_path):
    # A HAL name is never parsed as a board pin, so it cannot clash with
    # one or name an unknown MCU.
    payload = _payload(tmp_path, "[temperature_sensor y]\nsensor_type: hal\nsensor_pin: my_comp.0.temp\n")
    assert not [d for d in validate_machine(payload) if d.is_error]


def test_name_taken_by_heater_sensor(tmp_path):
    with pytest.raises(DuplicateTemperatureSensorError):
        _payload(tmp_path, "[temperature_sensor bed]\nsensor_type: hal\nsensor_pin: a.b\n")


def test_uppercase_name_is_unsupported(tmp_path):
    with pytest.raises(UnsupportedSectionError):
        _payload(tmp_path, "[temperature_sensor Chamber]\nsensor_type: hal\nsensor_pin: a.b\n")


def test_heater_cannot_read_a_hal_sensor(tmp_path):
    payload = _payload(tmp_path)
    payload["tools"][0]["sensor"] = "host"
    codes = {d.code for d in validate_machine(payload) if d.is_error}
    assert "E_HEATER_HAL_SENSOR" in codes


def test_io_pin_name_conflicts_with_sensor(tmp_path):
    payload = _payload(tmp_path, "[output_pin host]\npin: PB0\n")
    codes = {d.code for d in validate_machine(payload) if d.is_error}
    assert "E_IO_ID_CONFLICT" in codes
