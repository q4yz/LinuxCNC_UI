"""``[adxl345] cs_pin: <node>:PB12``: the CAN node's accelerometer (Remora-m8p
CAN_PROTOCOL.md) -> two hub process variables, the node's ADXL345 module,
a sampler for the resonance test."""
from __future__ import annotations

import json

import pytest

from MachineConfigParser import InvalidValueError, MachineConfigParser
from services.halcompiler import compile_machine_hal, render_webgui_connections, validate_machine
from services.halcompiler.HalAssembler import HalAssembler
from services.machineconfig.hardware_json_generator import build_hardware_json

BASE = """
[mcu]
connection: remora-spi

[mcu ebb]
connection: remora-can
canbus_uuid: 0e0d81e4210c
can_node: 1

[stepper_x]
step_pin: PF13
dir_pin: PF12
position_endstop: 0
position_max: 200

[estop]
"""


def _payload(adxl="[adxl345]\ncs_pin: ebb:PB12\naxes_map: -y,x,z\n", extra=""):
    return build_hardware_json(MachineConfigParser().parse_string(BASE + adxl + extra), "m")


def test_node_module_process_variables_and_sampler():
    payload = _payload()
    assert payload["adxl345"]["cs_pin"] == "ebb:PB12"
    assert not [d for d in validate_machine(payload) if d.is_error]
    hal = compile_machine_hal(payload)
    for line in ("net adxl345-x <= remora.PV.0", "net adxl345-y <= remora.PV.1",
                 "loadrt sampler depth=4000 cfg=ff", "addf sampler.0 servo-thread",
                 "net adxl345-x => sampler.0.pin.0", "net adxl345-y => sampler.0.pin.1"):
        assert line in hal, line
    config = json.loads(HalAssembler(payload).assemble().files["config_mcu.txt"])
    assert not any(m.get("Type") == "ADXL345" for m in config["Modules"])  # on the node, not the hub
    module = next(m for m in config["CAN"]["Nodes"][0]["Modules"] if m["Type"] == "ADXL345")
    assert module == {"Type": "ADXL345", "Comment": "adxl345", "CS Pin": "PB_12", "X PV[i]": 0, "Y PV[i]": 1,
                      "Axes Map": "-y,x,z", "Range": 16, "Rate": 3200}
    assert "net adxl345-record webgui.accel-record => sampler.0.enable" in render_webgui_connections(payload)


def test_other_spi_pins():
    payload = _payload("[adxl345]\ncs_pin: ebb:PA4\nspi_software_sclk_pin: ebb:PA5\nspi_software_mosi_pin: PA7\n"
                       "spi_software_miso_pin: ebb:PA6\nrate: 400\n")
    config = json.loads(HalAssembler(payload).assemble().files["config_mcu.txt"])
    module = next(m for m in config["CAN"]["Nodes"][0]["Modules"] if m["Type"] == "ADXL345")
    assert (module["CS Pin"], module["SCK Pin"], module["MOSI Pin"], module["MISO Pin"], module["Rate"]) == (
        "PA_4", "PA_5", "PA_7", "PA_6", 400)


def test_host_adxl_has_no_hal():
    payload = _payload("[adxl345]\nspi_device: /dev/spidev1.1\n")
    assert "sampler" not in compile_machine_hal(payload)
    assert "accel-record" not in render_webgui_connections(payload)


@pytest.mark.parametrize("adxl, match", [
    ("[adxl345]\ncs_pin: PB12\n", "CAN node"),
    ("[adxl345]\ncs_pin: ebb:PB12\nspi_software_sclk_pin: mcu:PB10\n", "a pin of ebb"),
    ("[adxl345]\ncs_pin: ebb:PB12\nrate: 300\n", "rate"),
    ("[adxl345]\nrate: 100\n", "rate"),
])
def test_invalid(adxl, match):
    with pytest.raises(InvalidValueError, match=match):
        _payload(adxl)


def test_process_variable_budget():
    sensors = "".join(f"[temperature_sensor t{i}]\nsensor_type: Generic 3950\nsensor_pin: PA{i}\n" for i in range(5))
    with pytest.raises(ValueError, match="process variables"):
        compile_machine_hal(_payload(extra=sensors))
