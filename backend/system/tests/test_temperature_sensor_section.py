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
from services.halcompiler.components.TemperatureSensorHalMapper import loaded_components

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
sensor_type: temperature_host
thermal_zone: 2

[temperature_sensor mcu]
sensor_type: temperature_mcu
{extra}
"""

HOST_LOAD = (
    "loadusr -Wn rpi-monitor env RPI_MONITOR_TEMP_FILE=/sys/class/thermal/thermal_zone2/temp "
    "python3 /usr/local/bin/rpi-monitor 1.0"
)


def _payload(tmp_path, extra=""):
    cfg = tmp_path / "machine.cfg"
    cfg.write_text(CFG.format(extra=extra), encoding="utf-8")
    from services.machineconfig.hardware_json_generator import build_hardware_json
    return json.loads(json.dumps(build_hardware_json(MachineConfigParser().parse(cfg), "sensors")))


def _errors(payload, user_hal=""):
    codes = {d.code for d in validate_machine(payload) if d.is_error}
    if codes:
        return codes
    try:
        compile_machine_hal(payload, user_hal)
    except ValueError as exc:
        return {word for word in str(exc).split() if word.startswith("E_")}
    return set()


def test_sections_reach_hardware_json(tmp_path):
    assert _payload(tmp_path)["temperature_sensors"] == [
        {"id": "bed", "pin": "PF3", "type": "Generic 3950"},
        {"id": "chamber", "pin": "PF5", "type": "Generic 3950"},
        {"id": "host", "pin": "rpi-monitor.cpu-temp", "type": "temperature_host", "thermal_zone": 2},
        {"id": "mcu", "pin": "mcu", "type": "temperature_mcu"},
    ]


def test_compiles_clean(tmp_path):
    assert _errors(_payload(tmp_path)) == set()


def test_host_loads_rpi_monitor_once_with_its_zone(tmp_path):
    hal = compile_machine_hal(_payload(tmp_path))
    assert hal.count("loadusr -Wn rpi-monitor") == 1
    assert HOST_LOAD in hal
    assert "net host-PV <= rpi-monitor.cpu-temp" in hal


def test_host_without_zone_uses_the_component_default(tmp_path):
    payload = _payload(tmp_path)
    del payload["temperature_sensors"][2]["thermal_zone"]
    assert "loadusr -Wn rpi-monitor python3 /usr/local/bin/rpi-monitor 1.0" in compile_machine_hal(payload)


def test_mcu_takes_the_next_free_pv_with_its_module(tmp_path):
    payload = _payload(tmp_path)
    hal = compile_machine_hal(payload)
    # bed PV.0, chamber PV.1, then the MCU's own temperature.
    assert "net bed-PV <= remora.PV.0" in hal
    assert "net chamber-PV <= remora.PV.1" in hal
    assert "net mcu-PV <= remora.PV.2" in hal
    modules = json.loads(HalAssembler(payload).assemble().files["config_mcu.txt"])["Modules"]
    assert {"Name": "mcu_temp", "Thread": "Servo", "Type": "MCU Temperature", "Comment": "mcu",
            "PV[i]": 2} in modules
    assert [m["Comment"] for m in modules if m["Type"] == "Temperature"] == ["bed", "chamber"]


def test_board_thermistor_gets_firmware_module(tmp_path):
    config = json.loads(HalAssembler(_payload(tmp_path)).assemble().files["config_mcu.txt"])
    modules = {m["Comment"]: m for m in config["Modules"] if m.get("Type") == "Temperature"}
    assert modules["chamber"]["PV[i]"] == 1
    assert modules["chamber"]["Thermistor"]["Pin"] == "PF_5"


def test_webgui_bindings_reach_the_plot(tmp_path):
    lines = render_webgui_connections(_payload(tmp_path)).splitlines()
    for sensor in ("bed", "chamber", "host", "mcu"):
        assert lines.count(f"net {sensor}-PV => webgui.{sensor}") == 1


# -- type: hal ----------------------------------------------------------------- #

USER_HAL = "loadusr -Wn mysensor mysensor-program\n"
HAL_SENSOR = "[temperature_sensor probe]\nsensor_type: hal\nsensor_pin: {pin}\n"


def test_hal_pin_of_a_user_hal_component(tmp_path):
    payload = _payload(tmp_path, HAL_SENSOR.format(pin="mysensor.temp"))
    assert _errors(payload, USER_HAL) == set()
    # Wired after user.hal (which loads the component), not in machine.hal.
    assert "mysensor" not in compile_machine_hal(payload, USER_HAL)
    lines = render_webgui_connections(payload).splitlines()
    assert lines.index("net probe-PV <= mysensor.temp") < lines.index("net probe-PV => webgui.probe")


def test_hal_pin_nothing_loads(tmp_path):
    payload = _payload(tmp_path, HAL_SENSOR.format(pin="mysensor.temp"))
    assert _errors(payload) == {"E_HAL_PIN_NO_COMPONENT"}


def test_hal_pin_of_the_host_monitor(tmp_path):
    # rpi-monitor is loaded by the temperature_host sensor: its load pin works.
    assert _errors(_payload(tmp_path, HAL_SENSOR.format(pin="rpi-monitor.cpu-load"))) == set()


def test_hal_pin_already_wired(tmp_path):
    # The host sensor's own pin, a second time (the first hal form): a second host sensor.
    assert "E_HOST_TEMP_SHARED" in _errors(_payload(tmp_path, HAL_SENSOR.format(pin="rpi-monitor.cpu-temp")))
    # A pin user.hal already put on a signal.
    payload = _payload(tmp_path, HAL_SENSOR.format(pin="mysensor.temp"))
    assert _errors(payload, USER_HAL + "net my-temp <= mysensor.temp\n") == {"E_HAL_PIN_IN_USE"}


def test_hal_signal_is_bound_directly(tmp_path):
    payload = _payload(tmp_path, HAL_SENSOR.format(pin="cpu-temp"))
    assert _errors(payload) == set()
    assert "net cpu-temp => webgui.probe" in render_webgui_connections(payload).splitlines()


def test_remora_pin_is_refused(tmp_path):
    # The case that aborted LinuxCNC: remora.PV.1 is the next thermistor's slot.
    assert _errors(_payload(tmp_path, HAL_SENSOR.format(pin="remora.PV.1"))) == {"E_HAL_PIN_GENERATED"}


def test_loaded_components():
    hal = """
loadrt remora-spi PRU_base_freq=20000
loadrt and2 names=heat-ok-a,heat-ok-b
loadrt pid count=2  # comment
loadusr -Wn rpi-monitor env X=1 python3 /usr/local/bin/rpi-monitor 1.0
loadusr -W vfdmod vfd.ini
"""
    assert loaded_components(hal) == {"remora", "heat-ok-a", "heat-ok-b", "pid", "rpi-monitor", "vfdmod"}


# -- one each, and the right board --------------------------------------------- #


def test_host_declared_twice(tmp_path):
    extra = "[temperature_sensor host2]\nsensor_type: temperature_host\n"
    assert "E_HOST_TEMP_SHARED" in _errors(_payload(tmp_path, extra))


def test_mcu_declared_twice(tmp_path):
    extra = "[temperature_sensor mcu2]\nsensor_type: temperature_mcu\n"
    assert "E_MCU_TEMP_SHARED" in _errors(_payload(tmp_path, extra))


def test_mcu_needs_a_remora_board(tmp_path):
    payload = _payload(tmp_path)
    payload["mcus"][0]["connection"] = "parport"
    assert "E_MCU_TEMP_NO_REMORA" in {d.code for d in validate_machine(payload) if d.is_error}


# -- parser -------------------------------------------------------------------- #


def test_missing_keys(tmp_path):
    with pytest.raises(MissingRequiredKeywordError):
        _payload(tmp_path, "[temperature_sensor x]\nsensor_type: hal\n")
    with pytest.raises(MissingRequiredKeywordError):
        _payload(tmp_path, "[temperature_sensor x]\nsensor_pin: PF6\n")


@pytest.mark.parametrize("kind", ["temperature_host", "temperature_mcu"])
def test_pinless_types_take_no_pin(tmp_path, kind):
    with pytest.raises(InvalidValueError):
        _payload(tmp_path, f"[temperature_sensor x]\nsensor_type: {kind}\nsensor_pin: a.b\n")


def test_thermal_zone_only_for_the_host(tmp_path):
    with pytest.raises(InvalidValueError):
        _payload(tmp_path, "[temperature_sensor x]\nsensor_type: hal\nsensor_pin: a.b\nthermal_zone: 1\n")


def test_bad_hal_name(tmp_path):
    with pytest.raises(InvalidValueError):
        _payload(tmp_path, "[temperature_sensor x]\nsensor_type: hal\nsensor_pin: a b\n")


def test_unknown_mcu_on_board_pin(tmp_path):
    with pytest.raises(UndefinedMcuError):
        _payload(tmp_path, "[temperature_sensor x]\nsensor_type: Generic 3950\nsensor_pin: ebb:PA3\n")


def test_name_taken_by_heater_sensor(tmp_path):
    with pytest.raises(DuplicateTemperatureSensorError):
        _payload(tmp_path, "[temperature_sensor bed]\nsensor_type: hal\nsensor_pin: a.b\n")


def test_uppercase_name_is_unsupported(tmp_path):
    with pytest.raises(UnsupportedSectionError):
        _payload(tmp_path, "[temperature_sensor Chamber]\nsensor_type: hal\nsensor_pin: a.b\n")


def test_heater_cannot_read_a_pinless_sensor(tmp_path):
    payload = _payload(tmp_path)
    payload["tools"][0]["sensor"] = "host"
    assert "E_HEATER_HAL_SENSOR" in {d.code for d in validate_machine(payload) if d.is_error}


def test_io_pin_name_conflicts_with_sensor(tmp_path):
    payload = _payload(tmp_path, "[output_pin host]\npin: PB0\n")
    assert "E_IO_ID_CONFLICT" in {d.code for d in validate_machine(payload) if d.is_error}


@pytest.mark.parametrize(
    ("pin", "kind"), [("rpi-monitor.cpu-temp", "temperature_host"), ("remora.mcu-temp", "temperature_mcu")]
)
def test_the_first_hal_form_stays_accepted(tmp_path, pin, kind):
    src = CFG.format(extra="").replace(
        "[temperature_sensor host]\nsensor_type: temperature_host\nthermal_zone: 2\n\n"
        "[temperature_sensor mcu]\nsensor_type: temperature_mcu\n", ""
    ) + f"[temperature_sensor old]\nsensor_type: hal\nsensor_pin: {pin}\n"
    cfg = tmp_path / "machine.cfg"
    cfg.write_text(src, encoding="utf-8")
    from services.machineconfig.hardware_json_generator import build_hardware_json
    payload = build_hardware_json(MachineConfigParser().parse(cfg), "sensors")
    old = next(s for s in payload["temperature_sensors"] if s["id"] == "old")
    assert old["type"] == kind
    assert _errors(payload) == set()
