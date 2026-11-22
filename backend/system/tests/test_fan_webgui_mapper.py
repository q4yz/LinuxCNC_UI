"""FanWebguiMapper — `webgui_connections.hal` binding for one `kind:
"part"` fan. Plain passthrough — the operator/G-code writes
`webgui.<id>`, `FanHalMapper` binds the physical pin elsewhere.
"""

from __future__ import annotations

from services.halcompiler.components.FanWebguiMapper import FanWebguiMapper
from models.machineconfig.HardwareJsonModels import Fan


def _fan_lines(fan):
    return FanWebguiMapper.to_lines(Fan.model_validate({"pin": "", **fan}))



def test_binds_webgui_id_straight_into_the_sp_signal():
    lines = _fan_lines({"id": "fan"})
    assert "net fan-SP <= webgui.fan" in lines


def test_bare_id_no_suffix_even_for_a_heater_derived_fan_id():
    lines = _fan_lines({"id": "fan_heater_extruder"})
    assert "net fan_heater_extruder-SP <= webgui.fan_heater_extruder" in lines
