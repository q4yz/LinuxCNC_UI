"""``TemperatureService.preload_hal_pins`` must reuse ``ToolsService``'s
already-built heater pins, not rebuild its own.

Real regression: it used to call ``HeaterMapper.from_dict_to_HeaterPins``
a second time for every heater/extruder tool. ``ToolsService`` had
already built the exact same pins moments earlier (``machine/main.py``
always preloads tools before temperature), so this re-registered the
same three HAL pin names per heater — harmless (``HalPin``'s own dedup
guard silently drops the second registration) but logged a "double
registration" warning on every single startup, for every heater's
target-temperature/reading/fan pin.

Tool ids here are unique to this test file (never used by any other
test in the suite) so identity comparisons below cannot accidentally
pass because some *other* test already registered the same pin name
under ``HalPin``'s process-wide registry.
"""

from __future__ import annotations

from dtos.tools import ExtruderPins, HeaterPins
import services.TemperatureService as temperature_service_mod
import services.ToolsService as tools_service_mod

_BED_TOOL = {
    "id": "heater_dedup_test_bed",
    "type": "heated_bed",
    "sensor": "dedup_test_bed_sensor",
    "min_temp": 0.0,
    "max_temp": 130.0,
}
_EXTRUDER_TOOL = {
    "id": "heater_dedup_test_extruder",
    "type": "extruder",
    "sensor": "dedup_test_extruder_sensor",
    "min_temp": 0.0,
    "max_temp": 250.0,
}


def test_temperature_service_reuses_tools_services_heater_pins(monkeypatch):
    monkeypatch.setattr(
        tools_service_mod, "get_tools", lambda: [_BED_TOOL, _EXTRUDER_TOOL]
    )
    monkeypatch.setattr(temperature_service_mod, "get_temperature_sensors", lambda: [])

    tools = tools_service_mod.ToolsService()
    tools.preload_hal_pins()
    monkeypatch.setattr(temperature_service_mod, "get_tools_service", lambda: tools)

    temperature = temperature_service_mod.TemperatureService()
    temperature.preload_hal_pins()

    tool_heater_pins = {
        (p.heater if isinstance(p, ExtruderPins) else p).id: (
            p.heater if isinstance(p, ExtruderPins) else p
        )
        for p in tools.get_halpins()
        if isinstance(p, (HeaterPins, ExtruderPins))
    }
    assert set(tool_heater_pins) == {"heater_dedup_test_bed", "heater_dedup_test_extruder"}

    temperature_heater_pins = {
        p.id: p for p in temperature.get_halpins() if isinstance(p, HeaterPins)
    }
    assert set(temperature_heater_pins) == set(tool_heater_pins)

    # The exact same objects — proof nothing rebuilt them (and so
    # nothing re-registered their HAL pins a second time).
    for tool_id, heater_pins in tool_heater_pins.items():
        assert temperature_heater_pins[tool_id] is heater_pins
