"""Remora CAN expansion end to end: ``[mcu toolhead] connection:
remora-can`` in the ``.cfg`` -> ``hardware.json`` -> the hub's
``config.txt`` ``"CAN"`` block and the E-stop chain in machine.hal
(Remora-m8p ``CAN_PROTOCOL.md``)."""
from __future__ import annotations

import json

import pytest

from MachineConfigParser import InvalidValueError, MachineConfigParser
from services.halcompiler import compile_machine_hal, validate_machine
from services.halcompiler.HalAssembler import HalAssembler
from services.machineconfig.hardware_json_generator import build_hardware_json

CFG = """
[mcu]
connection: remora-spi
board: BTT MANTA M8P
{hub}

[mcu toolhead]
connection: remora-can
canbus_uuid: 0E0D81E4210C
{node}

[machine]
kinematics: cartesian
max_velocity: 300
max_accel: 3000

[stepper_x]
step_pin: PF13
dir_pin: PF12
enable_pin: !PF14
endstop_pin: toolhead:^PB9
position_endstop: 0
position_max: 200

[estop]
{estop}
"""


def _payload(tmp_path, hub="", node="", estop=""):
    cfg = tmp_path / "machine.cfg"
    cfg.write_text(CFG.format(hub=hub, node=node, estop=estop), encoding="utf-8")
    return json.loads(json.dumps(build_hardware_json(MachineConfigParser().parse(cfg), "can")))


def _assemble(payload):
    fragment = HalAssembler(payload).assemble()
    return fragment, json.loads(fragment.files["config_mcu.txt"])


def test_node_modules_go_into_the_hubs_can_block(tmp_path):
    payload = _payload(tmp_path, hub="can_bitrate: 500000")
    fragment, config = _assemble(payload)

    assert "config_toolhead.txt" not in fragment.files  # a node has no SD card
    can = config["CAN"]
    assert (can["Bitrate"], can["Status Bit"]) == (500000, 15)
    [node] = can["Nodes"]
    assert (node["UUID"], node["Node"], node["Comment"], node["Mandatory"]) == (
        "0e0d81e4210c", 1, "toolhead", "True",
    )
    # The endstop: hub bit 0, node dialect (Modifier instead of `^`), Lost State always Low.
    [module] = node["Modules"]
    assert (module["Pin"], module["Modifier"], module["Mode"], module["Data Bit"], module["Lost State"]) == (
        "PB_9", "Pull Up", "Input", 0, "Low",
    )
    assert not any(m.get("Pin") == "^PB_9" for m in config["Modules"])


def test_status_bit_latches_estop_when_a_mandatory_node_is_lost(tmp_path):
    text = compile_machine_hal(_payload(tmp_path))
    assert "net can-fault <= remora.input.15.not" in text
    assert "net can-fault => estop-latch.0.fault-in" in text
    assert "net estop-ext <= estop-latch.0.ok-out => iocontrol.0.emc-enable-in" in text
    assert "net remora-status <= remora.SPI-status => iocontrol.0.emc-enable-in" not in text


def test_status_bit_and_a_physical_fault_pin_are_ored(tmp_path):
    payload = _payload(tmp_path, hub="can_status_bit: 7", estop="fault_pin: toolhead:PB8")
    text = compile_machine_hal(payload)
    assert "loadrt or2 names=estop-fault-or" in text
    assert "net can-fault <= remora.input.07.not" in text
    assert "net estop-fault => estop-fault-or.in0" in text
    assert "net can-fault => estop-fault-or.in1" in text
    assert "net estop-fault-any <= estop-fault-or.out => estop-latch.0.fault-in" in text
    # Exactly one latch chain: the node's fault pin did not start a second one.
    assert text.count("=> iocontrol.0.emc-enable-in") == 1
    assert "addf estop-fault-or servo-thread" in text


def test_inputs_skip_the_status_bit(tmp_path):
    payload = _payload(tmp_path, hub="can_status_bit: 0")
    _fragment, config = _assemble(payload)
    assert config["CAN"]["Nodes"][0]["Modules"][0]["Data Bit"] == 1


def test_optional_nodes_need_no_status_bit(tmp_path):
    payload = _payload(tmp_path, node="mandatory: false")
    _fragment, config = _assemble(payload)
    assert "Status Bit" not in config["CAN"]
    assert config["CAN"]["Nodes"][0]["Mandatory"] == "False"
    assert "can-fault" not in compile_machine_hal(payload)


def test_a_node_output_is_always_safe_low(tmp_path):
    payload = _payload(tmp_path, estop="out_pin: toolhead:PB8")
    _fragment, config = _assemble(payload)
    out = next(m for m in config["CAN"]["Nodes"][0]["Modules"] if m["Mode"] == "Output")
    assert (out["Pin"], out["Data Bit"], out["Safe State"]) == ("PB_8", 0, "Low")
    assert "Lost State" not in out


# -- validation ----------------------------------------------------------- #


def _codes(payload):
    return {d.code for d in validate_machine(payload)}


def test_a_heater_on_a_node_is_rejected(tmp_path):
    payload = _payload(tmp_path)
    payload["fans"] = [{"id": "fan_part", "pin": "toolhead:PA0"}]
    assert "E_CAN_NODE_PIN" in _codes(payload)


def test_endstops_and_estop_pins_on_a_node_are_fine(tmp_path):
    payload = _payload(tmp_path, estop="fault_pin: toolhead:PB8\nout_pin: toolhead:PB7")
    assert not {c for c in _codes(payload) if c.startswith("E_CAN")}


def test_a_node_without_a_hub_is_rejected(tmp_path):
    payload = _payload(tmp_path, node="can_hub: nowhere")
    assert "E_CAN_NO_HUB" in _codes(payload)


def test_duplicate_uuids_and_node_numbers_are_rejected(tmp_path):
    payload = _payload(tmp_path, node="can_node: 2")
    twin = dict(payload["mcus"][1], id="second")
    payload["mcus"].append(twin)
    assert {"E_CAN_DUPLICATE_UUID", "E_CAN_NODE_NUMBER"} <= _codes(payload)


@pytest.mark.parametrize("node, key", [
    ("canbus_uuid: nothex", "canbus_uuid"),
    ("can_node: 16", "can_node"),
    ("mandatory: maybe", "mandatory"),
    ("lost_state: high", "lost_state"),  # not a key: every pin falls back to Low
])
def test_node_keys_are_checked(tmp_path, node, key):
    cfg = (CFG.format(hub="", node=node, estop="")
           .replace("canbus_uuid: 0E0D81E4210C\ncanbus_uuid: nothex", "canbus_uuid: nothex"))
    path = tmp_path / "machine.cfg"
    path.write_text(cfg, encoding="utf-8")
    with pytest.raises(Exception, match=key):
        MachineConfigParser().parse(path)


def test_can_keys_belong_to_their_side(tmp_path):
    path = tmp_path / "machine.cfg"
    path.write_text(CFG.format(hub="canbus_uuid: 0e0d81e4210c", node="", estop=""), encoding="utf-8")
    with pytest.raises(InvalidValueError, match="canbus_uuid"):
        MachineConfigParser().parse(path)
