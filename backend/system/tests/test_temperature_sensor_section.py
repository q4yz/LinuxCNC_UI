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
    # rpi-monitor is a component the generator knows: loaded once.
    assert hal.count("loadusr -Wn rpi-monitor python3 /usr/local/bin/rpi-monitor 1.0") == 1


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


def test_rpi_monitor_loaded_once_for_two_pins(tmp_path):
    hal = compile_machine_hal(
        _payload(tmp_path, "[temperature_sensor load]\nsensor_type: hal\nsensor_pin: rpi-monitor.cpu-load\n")
    )
    assert hal.count("loadusr -Wn rpi-monitor") == 1


def test_other_hal_component_is_not_loaded(tmp_path):
    payload = _payload(tmp_path)
    payload["temperature_sensors"] = [s for s in payload["temperature_sensors"] if s["id"] != "host"]
    assert "rpi-monitor" not in compile_machine_hal(payload)


MCU_TEMP = "[temperature_sensor mcu]\nsensor_type: hal\nsensor_pin: remora.mcu-temp\n"


def test_mcu_temp_gets_module_and_named_pin(tmp_path):
    payload = _payload(tmp_path, MCU_TEMP)
    assert not [d for d in validate_machine(payload) if d.is_error]
    fragment = HalAssembler(payload).assemble()
    hal = compile_machine_hal(payload)
    # bed PV.0, chamber PV.1, then the MCU's own temperature.
    assert "alias pin remora.PV.2 remora.mcu-temp" in hal
    assert "net mcu-PV <= remora.mcu-temp" in hal
    assert hal.index("alias pin remora.PV.2") < hal.index("net mcu-PV")
    modules = json.loads(fragment.files["config_mcu.txt"])["Modules"]
    assert {"Name": "mcu_temp", "Thread": "Servo", "Type": "MCU Temperature", "Comment": "mcu",
            "PV[i]": 2} in modules
    assert "net mcu-PV => webgui.mcu" in render_webgui_connections(payload).splitlines()


def test_mcu_temp_declared_twice(tmp_path):
    payload = _payload(tmp_path, MCU_TEMP + MCU_TEMP.replace("sensor mcu]", "sensor mcu2]"))
    assert "E_MCU_TEMP_SHARED" in {d.code for d in validate_machine(payload) if d.is_error}


def test_mcu_temp_needs_a_remora_board(tmp_path):
    payload = _payload(tmp_path, MCU_TEMP)
    payload["mcus"][0]["connection"] = "parport"
    assert "E_MCU_TEMP_NO_REMORA" in {d.code for d in validate_machine(payload) if d.is_error}


def test_threads_entry_follows_pru_base_freq(tmp_path):
    def config(payload):
        return json.loads(HalAssembler(payload).assemble().files["config_mcu.txt"])

    assert "Threads" not in config(_payload(tmp_path))
    payload = _payload(tmp_path)
    payload["mcus"][0]["pru_base_freq"] = 20000
    cfg = config(payload)
    assert cfg["Threads"] == [{"Thread": "Base", "Frequency": 20000}]
    assert list(cfg) == ["Board", "Threads", "Modules"]
    assert "PRU_base_freq=20000" in compile_machine_hal(payload)
