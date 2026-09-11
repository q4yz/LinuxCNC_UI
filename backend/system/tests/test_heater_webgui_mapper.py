"""HeaterWebguiMapper — `webgui_connections.hal` bindings for one heater.

Pin names verified against the real runtime consumer,
`common/mappers/tools/HeaterMapper.py::from_dict_to_HeaterPins` —
`suffix = tool_id.replace("heater", "")`, the reading pin named after
the sensor's own id. A heater's referenced fan gets no binding here —
`FanWebguiMapper` (`test_fan_webgui_mapper.py`) covers every
``kind: "part"`` fan uniformly now, whether a heater references it or
not (`.agent/component/fan.md`).
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


def test_a_fan_reference_gets_no_binding_here():
    """Real regression guard: this mapper used to also emit the fan's
    binding; now `FanWebguiMapper` owns every "part" fan uniformly."""
    lines = HeaterWebguiMapper.to_lines({"id": "heater_bed", "fan": "fan_heater_bed"})
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
