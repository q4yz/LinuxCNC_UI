"""``FansService.preload_hal_pins`` — the crash this closes:

``webgui_connections.hal`` (``FanWebguiMapper``) always emits
``net <id>-SP <= webgui.<id>`` for every ``kind: "part"`` fan, but
until this service existed nothing on the Python side ever created
that HAL pin for a fan no heater's own ``fan`` cross-reference
already covered — LinuxCNC refused to load with "Pin 'webgui.<id>'
does not exist" (see ``.agent/component/fan.md``'s documented gap).

Fan/tool ids here are unique to this test file so identity/membership
checks below cannot accidentally pass because some *other* test
already registered the same pin name under ``HalPin``'s process-wide
registry.
"""

from __future__ import annotations

from dtos.fans.FanDto import FanPins
import services.FansService as fans_service_mod
import services.ToolsService as tools_service_mod

_STANDALONE_FAN = {"id": "fans_test_standalone", "kind": "part", "pin": "PA8"}
_HEATER_FAN = {"id": "fans_test_heater_owned", "kind": "part", "pin": "PA9"}
_HEATER_ONLY_FAN = {"id": "fans_test_heater_kind", "kind": "heater", "pin": "PA10"}
_HEATER_TOOL = {
    "id": "fans_test_heater_tool",
    "type": "extruder",
    "sensor": "fans_test_sensor",
    "fan": "fans_test_heater_owned",
    "min_temp": 0.0,
    "max_temp": 250.0,
}


def test_standalone_part_fan_gets_its_own_webgui_pin(monkeypatch):
    monkeypatch.setattr(tools_service_mod, "get_tools", lambda: [])
    tools = tools_service_mod.ToolsService()
    tools.preload_hal_pins()
    monkeypatch.setattr(fans_service_mod, "get_tools_service", lambda: tools)
    monkeypatch.setattr(fans_service_mod, "get_fans", lambda: [_STANDALONE_FAN])

    fans = fans_service_mod.FansService()
    fans.preload_hal_pins()

    fan_pins = {p.id: p for p in fans.get_halpins()}
    assert set(fan_pins) == {"fans_test_standalone"}
    assert fan_pins["fans_test_standalone"].speed.get_pin_name() == "fans_test_standalone"


def test_fan_already_claimed_by_a_heaters_own_fan_field_is_not_re_registered(monkeypatch):
    """The real dedup this closes: a ``part`` fan referenced by a
    heater's ``fan`` field is already a ``HeaterPins.fan`` HAL pin
    (``ToolsService``) — ``FansService`` must not build a second,
    independent registration for the same pin name."""
    monkeypatch.setattr(tools_service_mod, "get_tools", lambda: [_HEATER_TOOL])
    tools = tools_service_mod.ToolsService()
    tools.preload_hal_pins()
    monkeypatch.setattr(fans_service_mod, "get_tools_service", lambda: tools)
    monkeypatch.setattr(fans_service_mod, "get_fans", lambda: [_HEATER_FAN])

    fans = fans_service_mod.FansService()
    fans.preload_hal_pins()

    assert fans.get_halpins() == []


def test_heater_kind_fan_gets_no_pin_at_all(monkeypatch):
    monkeypatch.setattr(tools_service_mod, "get_tools", lambda: [])
    tools = tools_service_mod.ToolsService()
    tools.preload_hal_pins()
    monkeypatch.setattr(fans_service_mod, "get_tools_service", lambda: tools)
    monkeypatch.setattr(fans_service_mod, "get_fans", lambda: [_HEATER_ONLY_FAN])

    fans = fans_service_mod.FansService()
    fans.preload_hal_pins()

    assert fans.get_halpins() == []


def test_preload_is_idempotent(monkeypatch):
    monkeypatch.setattr(tools_service_mod, "get_tools", lambda: [])
    tools = tools_service_mod.ToolsService()
    tools.preload_hal_pins()
    monkeypatch.setattr(fans_service_mod, "get_tools_service", lambda: tools)

    calls = {"n": 0}

    def _get_fans():
        calls["n"] += 1
        return [{"id": "fans_test_idempotent", "kind": "part"}]

    monkeypatch.setattr(fans_service_mod, "get_fans", _get_fans)

    fans = fans_service_mod.FansService()
    fans.preload_hal_pins()
    fans.preload_hal_pins()

    assert calls["n"] == 1
    assert isinstance(fans.get_halpins()[0], FanPins)
