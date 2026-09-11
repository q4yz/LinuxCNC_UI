"""render_webgui_connections — aggregates EstopWebguiMapper/
SpindleWebguiMapper/HeaterWebguiMapper/FanWebguiMapper over a
hardware.json payload.

Deliberately independent of `validate_machine`/`compile_machine_hal`
— a spindle or heater with a real pin still deserves a working UI
binding even if the rest of the machine doesn't compile yet.
"""

from __future__ import annotations

from services.halcompiler import render_webgui_connections


def test_empty_payload_yields_an_empty_string():
    assert render_webgui_connections({}) == ""


def test_no_spindle_or_heater_tools_yields_an_empty_string():
    payload = {"tools": [{"id": "spindle_analog", "type": "spindle_analog"}]}
    assert render_webgui_connections(payload) == ""


def test_binds_a_spindle_and_a_heater_together():
    payload = {
        "tools": [
            {"id": "spindle_digital", "run_pin": "vfd0:run-forward", "type": "spindle_digital"},
            {"id": "heater_bed", "sensor": "bed", "type": "heated_bed"},
        ]
    }
    text = render_webgui_connections(payload)
    assert "# Spindle: spindle_digital" in text
    assert "net spindle-speed-cmd => webgui.TargetRpm" in text
    assert "# Heater: heater_bed" in text
    assert "net heater_bed-SP <= webgui.target-temperature_bed" in text
    assert "net bed-PV => webgui.bed" in text


def test_estop_binding_appears_when_the_payload_declares_one():
    """Every real hardware.json has an `estop` key (required exactly
    once) — the binding is unconditional once it's present, regardless
    of whether fault_pin/out_pin are set."""
    text = render_webgui_connections({"estop": {}})
    assert "net estop-activate webgui.estop => halui.estop.activate" in text


def test_estop_and_spindle_and_heater_all_bind_together():
    payload = {
        "estop": {"fault_pin": "10"},
        "tools": [
            {"id": "spindle_digital", "run_pin": "vfd0:run-forward", "type": "spindle_digital"},
            {"id": "heater_bed", "sensor": "bed", "type": "heated_bed"},
        ],
    }
    text = render_webgui_connections(payload)
    assert "# Estop" in text
    assert "net estop-activate webgui.estop => halui.estop.activate" in text
    assert "# Spindle: spindle_digital" in text
    assert "# Heater: heater_bed" in text


def test_a_non_estop_dict_value_is_ignored_not_crashed():
    """A payload that carries some other truthy-but-wrong `estop`
    shape (a hand-edited fixture, a future format change) must not
    crash rendering — only a genuine dict triggers the binding."""
    assert render_webgui_connections({"estop": None}) == ""
    assert render_webgui_connections({"estop": "not-a-dict"}) == ""


def test_a_part_fan_binds_but_a_heater_fan_does_not():
    payload = {
        "fans": [
            {"id": "fan", "pin": "PA8", "kind": "part"},
            {"id": "heater_fan_heatbreak", "pin": "PA9", "kind": "heater"},
        ]
    }
    text = render_webgui_connections(payload)
    assert "net fan-SP <= webgui.fan" in text
    assert "heater_fan_heatbreak" not in text


def test_kind_defaults_to_part_when_absent_from_a_fan_record():
    text = render_webgui_connections({"fans": [{"id": "fan", "pin": "PA8"}]})
    assert "net fan-SP <= webgui.fan" in text


def test_a_fan_sharing_a_pin_in_duplicate_pin_overrides_gets_no_binding():
    """Real regression guard: HalAssembler renames a shared-pin fan's
    signal onto whatever else already claims the pin, so a standalone
    webgui binding here would reference a signal machine.hal never
    actually uses."""
    payload = {
        "fans": [{"id": "fan_extruder", "pin": "mcu:PA2", "kind": "part"}],
        "duplicate_pin_overrides": ["mcu:PA2"],
    }
    assert render_webgui_connections(payload) == ""


def test_a_non_dict_fans_entry_is_skipped_not_crashed():
    payload = {"fans": ["not-a-dict", {"id": "fan", "pin": "PA8"}]}
    text = render_webgui_connections(payload)
    assert "net fan-SP <= webgui.fan" in text


def test_a_non_dict_tools_entry_is_skipped_not_crashed():
    """`validate_machine` is what should catch a genuinely malformed
    ``hardware.json`` — this only has to survive a non-dict entry
    sitting next to a real one, the same defensive check the
    assembler's own `_spindle_fragments`/`_heater_fragments` use."""
    payload = {
        "tools": [
            "not-a-dict",
            {"id": "spindle_digital", "run_pin": "vfd0:run-forward", "type": "spindle_digital"},
        ]
    }
    text = render_webgui_connections(payload)
    assert "# Spindle: spindle_digital" in text
