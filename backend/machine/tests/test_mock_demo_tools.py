"""Mock mode: a machine without heaters gets a demo extruder and bed, so
the Tools panel has something to show on a development PC."""
from __future__ import annotations

from hardware.mock import demo_tools


def test_added_when_the_machine_has_no_heater():
    payload = {"tools": [{"id": "spindle", "type": "spindle_digital"}], "temperature_sensors": []}
    out = demo_tools.with_demo_tools(payload)
    assert [t["id"] for t in out["tools"]] == ["spindle", "extruder", "heater_bed"]
    assert {s["id"] for s in out["temperature_sensors"]} == {"extruder", "bed"}
    assert payload["tools"] == [{"id": "spindle", "type": "spindle_digital"}]  # input untouched


def test_not_added_when_a_heater_is_configured():
    payload = {"tools": [{"id": "bed", "type": "heated_bed", "sensor": "bed"}]}
    assert demo_tools.with_demo_tools(payload) is payload


def test_can_be_turned_off(monkeypatch):
    monkeypatch.setenv(demo_tools.ENV_FLAG, "0")
    assert demo_tools.with_demo_tools({}) == {}


def test_the_mock_simulates_them():
    from hardware.mock.LinuxCNCMock import LinuxCNCMock

    mock = LinuxCNCMock()
    mock.register_hardware(demo_tools.with_demo_tools({}))
    mock.internal_hal.set_pin("webgui.target-temperature_bed", 60.0)
    mock.internal_hal.update(delta_time=5.0)
    assert mock.internal_hal.get_pin("webgui.bed") == 35.0  # 25 °C + 2 °C/s × 5 s
