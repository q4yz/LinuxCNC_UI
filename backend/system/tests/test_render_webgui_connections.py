"""render_webgui_connections — aggregates SpindleWebguiMapper/
HeaterWebguiMapper over a hardware.json payload's `tools[]`.

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
