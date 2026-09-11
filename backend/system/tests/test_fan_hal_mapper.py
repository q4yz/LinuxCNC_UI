"""FanHalMapper — `.agent/component/fan.md` § 3.

Two `kind`s, two entirely different control models:

* `"part"` — a plain direct pin route, operator/G-code commandable
  (the write side, `webgui.<id> => <id>-SP`, lives in
  `webgui_connections.hal` via `FanWebguiMapper`).
* `"heater"` — a `wcomp` (window comparator) + `conv_bit_float` +
  `scale` chain gates the fan on the referenced heater's own sensor
  reading; never commandable by webgui at all.
"""

from __future__ import annotations

from models.machineconfig.hal_fragment_models import PinRole
from services.halcompiler.components.FanHalMapper import FanHalMapper

_HEATER = {"id": "heater_extruder", "sensor": "extruder"}
_SENSOR = {"id": "extruder", "pin": "PF4"}


def test_part_fan_gets_exactly_one_pin_request_and_no_other_hal():
    fan = {"id": "fan", "pin": "PA8", "kind": "part"}
    fragment = FanHalMapper.to_fragment(fan, {}, {})

    assert fragment.loadrt == []
    assert fragment.addf == []
    assert fragment.setp == []
    assert fragment.nets == []
    [request] = fragment.requests
    assert request.signal == "fan-SP"
    assert request.role is PinRole.ANALOG_OUT
    assert request.pin.pin_id == "PA8"
    assert request.owner == "fan"


def test_kind_defaults_to_part_when_absent():
    fan = {"id": "fan", "pin": "PA8"}
    fragment = FanHalMapper.to_fragment(fan, {}, {})
    assert len(fragment.requests) == 1
    assert fragment.nets == []


def test_no_pin_means_an_entirely_empty_fragment():
    fan = {"id": "fan", "kind": "part"}
    fragment = FanHalMapper.to_fragment(fan, {}, {})
    assert fragment.requests == []
    assert fragment.nets == []


def test_heater_fan_wires_the_wcomp_conv_scale_chain():
    fan = {
        "id": "heater_fan_heatbreak_cooling_fan",
        "pin": "PA9",
        "kind": "heater",
        "heater": "heater_extruder",
        "heater_temp": 60,
        "fan_speed": 0.8,
    }
    fragment = FanHalMapper.to_fragment(
        fan, {"heater_extruder": _HEATER}, {"extruder": _SENSOR}
    )

    assert "loadrt wcomp names=wcomp-heater_fan_heatbreak_cooling_fan" in fragment.loadrt
    assert "loadrt conv_bit_float names=conv-heater_fan_heatbreak_cooling_fan" in fragment.loadrt
    assert "loadrt scale names=scale-heater_fan_heatbreak_cooling_fan" in fragment.loadrt

    assert "setp wcomp-heater_fan_heatbreak_cooling_fan.min 60" in fragment.setp
    assert "setp wcomp-heater_fan_heatbreak_cooling_fan.max 999.0" in fragment.setp
    # fan_speed (0.0-1.0, Klipper units) -> percent (this compiler's
    # own remora.SP.N convention, matching heater.md's PID CVmax /
    # watermark scale.gain defaults, both 100.0).
    assert "setp scale-heater_fan_heatbreak_cooling_fan.gain 80.0" in fragment.setp

    assert "net extruder-PV => wcomp-heater_fan_heatbreak_cooling_fan.in" in fragment.nets
    assert "net heater_fan_heatbreak_cooling_fan-SP <= scale-heater_fan_heatbreak_cooling_fan.out" in fragment.nets

    [request] = fragment.requests
    assert request.signal == "heater_fan_heatbreak_cooling_fan-SP"
    assert request.role is PinRole.ANALOG_OUT
    assert request.pin.pin_id == "PA9"


def test_heater_fan_defaults_match_klippers_own_documented_defaults():
    fan = {
        "id": "heater_fan",
        "pin": "PA9",
        "kind": "heater",
        "heater": "heater_extruder",
    }
    fragment = FanHalMapper.to_fragment(
        fan, {"heater_extruder": _HEATER}, {"extruder": _SENSOR}
    )
    assert "setp wcomp-heater_fan.min 50.0" in fragment.setp  # heater_temp default
    assert "setp scale-heater_fan.gain 100.0" in fragment.setp  # fan_speed 1.0 -> 100%


def test_heater_fan_with_no_matching_heater_is_an_honest_gap():
    fan = {"id": "heater_fan", "pin": "PA9", "kind": "heater", "heater": "ghost"}
    fragment = FanHalMapper.to_fragment(fan, {}, {})
    assert fragment.requests == []
    assert fragment.nets == []


def test_heater_fan_whose_heater_has_no_sensor_is_an_honest_gap():
    """Nothing to gate the fan on — the referenced heater declares no
    sensor at all, matching HeaterHalMapper's own "no sensor means no
    -PV signal" contract."""
    fan = {"id": "heater_fan", "pin": "PA9", "kind": "heater", "heater": "heater_bed"}
    fragment = FanHalMapper.to_fragment(
        fan, {"heater_bed": {"id": "heater_bed"}}, {}
    )
    assert fragment.requests == []
    assert fragment.nets == []
