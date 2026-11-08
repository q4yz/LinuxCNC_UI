"""``[neopixel NAME]``: ``.cfg`` -> hardware.json -> a Remora set point per
colour segment and the firmware "RGB" module (`.agent/component/neopixel.md`)."""
from __future__ import annotations

import json

import pytest

from MachineConfigParser import InvalidValueError, MachineConfigParser, MissingRequiredKeywordError
from services.halcompiler import compile_machine_hal, render_webgui_connections, validate_machine
from services.halcompiler.HalAssembler import HalAssembler
from services.machineconfig.hardware_json_generator import build_hardware_json

BASE = """
[mcu]
connection: remora-spi

[stepper_x]
step_pin: PF13
dir_pin: PF12
position_endstop: 0
position_max: 200

[estop]
"""
SB = """
[neopixel sb_leds]
pin: PD3
chain_count: 3
color_order: GRBW
segments: 1, 2-3
initial_RED: 1.0
initial_WHITE: 0.25
"""
NODE = """
[mcu ebb]
connection: remora-can
canbus_uuid: 0e0d81e4210c
can_node: 1
"""


def _payload(extra=SB):
    return build_hardware_json(MachineConfigParser().parse_string(BASE + extra), "m")


def test_reaches_hardware_json():
    assert _payload()["leds"] == [{
        "id": "sb_leds", "pin": "PD3", "chain_count": 3, "color_order": "GRBW",
        "segments": [[1, 1], [2, 2]], "initial": [1.0, 0.0, 0.0, 0.25],
    }]


def test_defaults_klipper():
    led = _payload("[neopixel case]\npin: PB15\n")["leds"][0]
    assert (led["chain_count"], led["color_order"], led["segments"]) == (1, "GRB", [[1, 1]])
    assert _payload("[neopixel case]\npin: PB15\nchain_count: 10\n")["leds"][0]["segments"] == [[1, 10]]
    # Klipper's per-LED order list, all the same order.
    assert _payload("[neopixel c]\npin: PB15\nchain_count: 2\ncolor_order: GRB, GRB\n")["leds"][0]["color_order"] == "GRB"


def test_set_points_and_rgb_module():
    payload = _payload()
    hal = compile_machine_hal(payload)
    assert "net sb_leds-rgb0 => remora.SP.0" in hal
    assert "net sb_leds-rgb1 => remora.SP.1" in hal
    modules = json.loads(HalAssembler(payload).assemble().files["config_mcu.txt"])["Modules"]
    assert {
        "Name": "rgb_sb_leds", "Thread": "Servo", "Type": "RGB", "Comment": "sb_leds", "Pin": "PD_3",
        "Chain Count": 3, "Color Order": "GRBW",
        "Segments": [{"First": 1, "Count": 1, "SP[i]": 0}, {"First": 2, "Count": 2, "SP[i]": 1}],
    } in modules
    lines = render_webgui_connections(payload).splitlines()
    assert "net sb_leds-rgb0 <= webgui.led-sb_leds-0" in lines
    assert "net sb_leds-rgb1 <= webgui.led-sb_leds-1" in lines


def test_on_a_can_node():
    payload = _payload(NODE + SB.replace("pin: PD3", "pin: ebb:PD3"))
    assert not [d for d in validate_machine(payload) if d.is_error]
    config = json.loads(HalAssembler(payload).assemble().files["config_mcu.txt"])
    node = config["CAN"]["Nodes"][0]
    assert any(m["Type"] == "RGB" and m["Pin"] == "PD_3" for m in node["Modules"])


def test_too_many_set_points():
    extra = "".join(f"[neopixel l{i}]\npin: P{p}\nchain_count: 2\nsegments: 1, 2\n" for i, p in enumerate(("A9", "B15", "C6", "D3")))
    with pytest.raises(ValueError, match="set points"):
        compile_machine_hal(_payload(extra))


def test_node_limit():
    extra = NODE + "[neopixel a]\npin: ebb:PD3\nchain_count: 5\nsegments: 1, 2, 3, 4, 5\n"
    assert "E_LED_LIMIT" in {d.code for d in validate_machine(_payload(extra)) if d.is_error}


def test_not_on_a_parport():
    extra = "[mcu pp]\nconnection: parallelport\ninterface: 0x378\n\n[neopixel a]\npin: pp:2\n"
    payload = _payload(extra)
    assert "E_LED_NOT_REMORA" in {d.code for d in validate_machine(payload) if d.is_error}


@pytest.mark.parametrize(
    ("extra", "error"),
    [
        ("[neopixel a]\nchain_count: 2\n", MissingRequiredKeywordError),
        ("[neopixel a]\npin: PD3\nchain_count: 0\n", InvalidValueError),
        ("[neopixel a]\npin: PD3\nchain_count: 65\n", InvalidValueError),
        ("[neopixel a]\npin: PD3\ncolor_order: GRG\n", InvalidValueError),
        ("[neopixel a]\npin: PD3\nchain_count: 2\ncolor_order: GRB, RGB\n", InvalidValueError),
        ("[neopixel a]\npin: PD3\nchain_count: 3\nsegments: 1, 3\n", InvalidValueError),      # LED 2 missing
        ("[neopixel a]\npin: PD3\nchain_count: 3\nsegments: 1-2, 2-3\n", InvalidValueError),  # overlap
        ("[neopixel a]\npin: PD3\ninitial_RED: 2\n", InvalidValueError),
    ],
)
def test_errors(extra, error):
    with pytest.raises(error):
        _payload(extra)
