"""``[output_pin NAME]`` / ``[input_pin NAME]`` end to end: ``.cfg`` ->
``hardware.json`` -> machine.hal, webgui_connections.hal, the INI's halui
MDI commands and their subroutines (`.agent/component/io_pins.md`)."""
from __future__ import annotations

import json

import pytest

from MachineConfigParser import InvalidValueError, MachineConfigParser
from services.halcompiler import compile_machine_hal, render_webgui_connections, validate_machine
from services.halcompiler.HalAssembler import HalAssembler
from services.halcompiler.components.IoPinHalMapper import mdi_commands
from services.machinetemplates.ini_template_generator import render_ini_template

CFG = """
[mcu]
connection: remora-spi

[stepper_x]
step_pin: PF13
dir_pin: PF12
position_endstop: 0
position_max: 200

[estop]

[input_pin my_custom_button]
pin: ^PA0  # pull-up
rising_ngc:
    (MSG, Button pressed)
    # a comment line
    M64 P0
falling_ngc:
    (MSG, Button released)

[output_pin case_light]
pin: PB0
value: 0
shutdown_value: 0

[output_pin dimmable_light]
pin: PB1
pwm: True
value: 0
cycle_time: 0.010
scale: 100
{extra}
"""


def _payload(tmp_path, extra=""):
    cfg = tmp_path / "machine.cfg"
    cfg.write_text(CFG.format(extra=extra), encoding="utf-8")
    from services.machineconfig.hardware_json_generator import build_hardware_json
    return json.loads(json.dumps(build_hardware_json(MachineConfigParser().parse(cfg), "io")))


def test_sections_reach_hardware_json(tmp_path):
    payload = _payload(tmp_path)
    assert payload["output_pins"] == [
        {"id": "case_light", "pin": "PB0", "pwm": False, "value": 0.0, "shutdown_value": 0.0,
         "cycle_time": 0.1, "scale": 1.0},
        {"id": "dimmable_light", "pin": "PB1", "pwm": True, "value": 0.0, "shutdown_value": 0.0,
         "cycle_time": 0.01, "scale": 100.0},
    ]
    assert payload["input_pins"] == [{
        "id": "my_custom_button", "pin": "^PA0",
        "rising_ngc": "(MSG, Button pressed)\nM64 P0", "falling_ngc": "(MSG, Button released)",
        "rising_halpin_set": [], "falling_halpin_set": [],
    }]


@pytest.mark.parametrize("extra, key", [
    ("[output_pin x]\npin: PB2\nshutdown_value: 1\n", "shutdown_value"),
    ("[output_pin x]\npin: PB2\nvalue: 0.5\n", "value"),
    ("[output_pin x]\npin: PB2\npwm: True\nscale: 10\nvalue: 11\n", "value"),
    ("[output_pin x]\npin: PB2\npwm: maybe\n", "pwm"),
    ("[output_pin x]\npin: PB2\ncycle_time: 0\n", "cycle_time"),
])
def test_bad_output_values_are_rejected(tmp_path, extra, key):
    with pytest.raises(InvalidValueError, match=key):
        _payload(tmp_path, extra)


def test_a_switch_is_a_digital_output_and_pwm_a_scaled_sp_channel(tmp_path):
    payload = _payload(tmp_path)
    assert not [d for d in validate_machine(payload) if d.is_error]
    text = compile_machine_hal(payload)
    assert "net case_light-out => remora.output.00" in text
    assert "setp dimmable_light-scale.gain 1" in text  # scale 100 = already percent
    assert "net dimmable_light-SP <= dimmable_light-scale.out" in text
    assert "net dimmable_light-SP => remora.SP.0" in text
    assert "net my_custom_button-in remora.input.00" in text
    assert "net my_custom_button-in => my_custom_button-released.in" in text

    config = json.loads(HalAssembler(payload).assemble().files["config_mcu.txt"])
    pwm = next(m for m in config["Modules"] if m.get("Comment") == "dimmable_light")
    assert (pwm["Type"], pwm["Period us"]) == ("PWM", 10000)


def test_scale_1_pwm_goes_to_percent(tmp_path):
    text = compile_machine_hal(_payload(tmp_path, "[output_pin dim2]\npin: PB2\npwm: True\n"))
    assert "setp dim2-scale.gain 100" in text


def test_webgui_drives_outputs_reads_inputs_and_fires_the_edges(tmp_path):
    lines = render_webgui_connections(_payload(tmp_path))
    assert "net case_light-out <= webgui.case_light" in lines
    assert "net dimmable_light-value webgui.dimmable_light => dimmable_light-scale.in" in lines
    assert "net my_custom_button-in => webgui.my_custom_button" in lines
    assert "net my_custom_button-in => halui.mdi-command-00" in lines
    assert "net my_custom_button-released my_custom_button-released.out => halui.mdi-command-01" in lines


def test_the_edges_are_halui_mdi_commands_calling_subroutines(tmp_path):
    commands = mdi_commands(_payload(tmp_path)["input_pins"])
    assert [c.ini_line for c in commands] == [
        "MDI_COMMAND = o<my_custom_button_rising> call",
        "MDI_COMMAND = o<my_custom_button_falling> call",
    ]
    assert commands[0].file_content == (
        "o<my_custom_button_rising> sub\n(MSG, Button pressed)\nM64 P0\n"
        "o<my_custom_button_rising> endsub\nM2\n"
    )
    ini = render_ini_template("io", [], None, [c.ini_line for c in commands])
    assert "[HALUI]\nMDI_COMMAND = o<my_custom_button_rising> call\nMDI_COMMAND = o<my_custom_button_falling> call" in ini
    assert ":subroutines" in ini
    assert ":subroutines" not in render_ini_template("io", [], None, [])


def test_an_io_name_may_not_repeat_another_component(tmp_path):
    payload = _payload(tmp_path, "[fan]\npin: PE6\n[output_pin fan]\npin: PB3\n")
    assert "E_IO_ID_CONFLICT" in {d.code for d in validate_machine(payload)}


def test_io_pins_count_as_claimed_pins(tmp_path):
    payload = _payload(tmp_path, "[output_pin dup]\npin: PB0\n")
    assert "E_PIN_CONFLICT" in {d.code for d in validate_machine(payload)}


# -- *_halpin_set: input edges set outputs in realtime HAL -------------------- #

DOOR = """
[input_pin door_switch]
pin: PA1
rising_halpin_set: case_light, 1
falling_halpin_set:
    case_light, 0
    dimmable_light, 40
falling_ngc: (MSG, Door opened)
"""


def test_halpin_sets_reach_hardware_json(tmp_path):
    door = next(p for p in _payload(tmp_path, DOOR)["input_pins"] if p["id"] == "door_switch")
    assert door["rising_halpin_set"] == [{"output": "case_light", "value": 1.0}]
    assert door["falling_halpin_set"] == [
        {"output": "case_light", "value": 0.0}, {"output": "dimmable_light", "value": 40.0},
    ]


def test_a_targeted_output_is_latched_last_event_wins(tmp_path):
    payload = _payload(tmp_path, DOOR)
    assert not [d for d in validate_machine(payload) if d.is_error]
    text = compile_machine_hal(payload)
    # The input edges: one pulse each.
    assert "net door_switch-in => door_switch-rising-edge.in" in text
    assert "setp door_switch-falling-edge.in-edge 0" in text
    # case_light: UI stage, then rising -> 1, falling -> 0, fed back.
    assert "net case_light-ui-pulse <= case_light-ui-edge.out => case_light-set0.sel" in text
    assert "net case_light-latched => case_light-set0.in0" in text
    assert "net door_switch-rising => case_light-set1.sel" in text
    assert "setp case_light-set1.in1 1" in text
    assert "net door_switch-falling => case_light-set2.sel" in text
    assert "setp case_light-set2.in1 0" in text
    assert "net case_light-latched <= case_light-set2.out" in text
    # switched: latched > 0.5 drives the pin; one writer only.
    assert "net case_light-out <= case_light-on.out" in text
    assert text.count("case_light-out <=") == 1
    # PWM target: the latch feeds the scale.
    assert "net dimmable_light-latched => dimmable_light-scale.in" in text

    lines = render_webgui_connections(payload)
    assert "net case_light-ui-value webgui.case_light => case_light-set0.in1" in lines
    assert "net case_light-ui-set webgui.case_light-set => case_light-ui-edge.in" in lines
    assert "net case_light-latched => webgui.case_light-state" in lines
    assert "net case_light-out <= webgui.case_light" not in lines  # no second writer


@pytest.mark.parametrize("extra, message", [
    ("[input_pin b]\npin: PA2\nrising_halpin_set: nothing, 1\n", "no [output_pin]"),
    ("[input_pin b]\npin: PA2\nrising_halpin_set: case_light, 0.5\n", "0 or 1"),
    ("[input_pin b]\npin: PA2\nrising_halpin_set: dimmable_light, 120\n", "0 ... 100"),
])
def test_halpin_set_targets_and_values_are_checked(tmp_path, extra, message):
    errors = [d for d in validate_machine(_payload(tmp_path, extra)) if d.code == "E_IO_TARGET"]
    assert len(errors) == 1 and message in errors[0].message


def test_a_malformed_halpin_set_is_rejected(tmp_path):
    with pytest.raises(InvalidValueError, match="rising_halpin_set"):
        _payload(tmp_path, "[input_pin b]\npin: PA2\nrising_halpin_set: case_light\n")
