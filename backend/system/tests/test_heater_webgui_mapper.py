"""HeaterWebguiMapper — `webgui_connections.hal` bindings for one heater.

Pin names verified against the real runtime consumer,
`common/mappers/tools/HeaterMapper.py::from_dict_to_HeaterPins` —
`suffix = tool_id.replace("heater", "")`, the reading pin named after
the sensor's own id, the fan pin named after the fan's own id (no
`-SP` suffix on the webgui side).
"""

from __future__ import annotations

from services.halcompiler.components.HeaterWebguiMapper import HeaterWebguiMapper


def test_setpoint_is_always_bound_as_a_write_into_the_sp_signal():
    lines = HeaterWebguiMapper.to_lines({"id": "heater_bed"})
    assert "net heater_bed-SP <= webgui.target-temperature_bed" in lines


def test_sensor_reading_is_bound_by_the_sensors_own_id():
    lines = HeaterWebguiMapper.to_lines({"id": "heater_bed", "sensor": "bed"})
    assert "net bed-PV => webgui.bed" in lines


def test_no_sensor_means_no_reading_binding():
    """`HeaterHalMapper` creates no `-PV` signal at all without a
    sensor — nothing here to route into webgui either."""
    lines = HeaterWebguiMapper.to_lines({"id": "heater_bed"})
    assert not any("-PV" in line for line in lines)


def test_fan_is_bound_by_its_own_bare_id_not_suffixed_with_sp():
    lines = HeaterWebguiMapper.to_lines({"id": "heater_bed", "fan": "fan_heater_bed"})
    assert "net fan_heater_bed-SP <= webgui.fan_heater_bed" in lines


def test_no_fan_reference_means_no_fan_binding():
    lines = HeaterWebguiMapper.to_lines({"id": "heater_bed"})
    assert not any("fan" in line for line in lines)


def test_extruder_suffix_derives_from_its_own_id():
    lines = HeaterWebguiMapper.to_lines({"id": "heater_extruder", "sensor": "extruder"})
    assert "net heater_extruder-SP <= webgui.target-temperature_extruder" in lines
    assert "net extruder-PV => webgui.extruder" in lines


def test_a_second_extruder_gets_its_own_distinct_pins():
    lines = HeaterWebguiMapper.to_lines(
        {"id": "heater_extruder_test", "sensor": "extruder_test", "fan": "fan_heater_extruder_test"}
    )
    assert "net heater_extruder_test-SP <= webgui.target-temperature_extruder_test" in lines
    assert "net extruder_test-PV => webgui.extruder_test" in lines
    assert "net fan_heater_extruder_test-SP <= webgui.fan_heater_extruder_test" in lines
