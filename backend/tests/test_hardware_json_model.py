"""Tests for the ``hardware.json`` v2 Pydantic model and its cross-reference validator."""

from __future__ import annotations

import pytest

from modules.machineconfig.models.hardware_json_models import (
    Axis,
    Driver,
    Endstop,
    Fan,
    HardwareJson,
    Stepper,
    TemperatureSensor,
    Tool,
    model_validate,
    to_dict,
)


# ---------------------------------------------------------------------- #
# Helpers                                                                   #
# ---------------------------------------------------------------------- #


def _minimal_payload() -> dict:
    """A minimal but valid ``hardware.json`` v2 payload.

    Every entity is present with the bare minimum fields the model
    requires. Tests mutate this dict to add or break fields.
    """
    return {
        "version": "2.0",
        "machine": "test",
        "source": "KlipperToLinuxCNCCompiler",
        "kinematics": "cartesian",
        "hal_type": "remora",
        "axes": [
            {"id": "x", "steppers": ["stepper_x"]},
        ],
        "steppers": [
            {
                "id": "stepper_x",
                "driver": "driver_x",
                "step_pin": "PF13",
                "dir_pin": "PF12",
                "enable_pin": "!PF14",
                "microsteps": 16,
                "rotation_distance": 40.0,
            },
        ],
        "drivers": [
            {"id": "driver_x", "type": "TMC2209"},
        ],
        "endstops": [],
        "tools": [],
        "temperature_sensors": [],
        "fans": [],
    }


# ---------------------------------------------------------------------- #
# Top-level validation                                                      #
# ---------------------------------------------------------------------- #


class TestRootValidation:
    def test_version_must_be_2_0(self) -> None:
        payload = _minimal_payload()
        payload["version"] = "1.0"
        with pytest.raises(ValueError, match="version"):
            model_validate(payload)

    def test_extra_top_level_field_rejected(self) -> None:
        payload = _minimal_payload()
        payload["unknown_field"] = 1
        with pytest.raises(ValueError, match="unknown_field"):
            model_validate(payload)

    def test_empty_lists_are_allowed(self) -> None:
        """A machine with no tools, sensors, fans, or endstops is valid."""

        payload = _minimal_payload()
        model = model_validate(payload)
        assert model.tools == []
        assert model.temperature_sensors == []
        assert model.fans == []
        assert model.endstops == []
        assert model.axes == [Axis(id="x", steppers=["stepper_x"])]

    def test_to_dict_omits_none_values(self) -> None:
        """The serialised payload drops None values to keep the JSON lean."""

        payload = _minimal_payload()
        model = model_validate(payload)
        serialised = to_dict(model)
        flat = str(serialised)
        assert "None" not in flat


# ---------------------------------------------------------------------- #
# ID uniqueness                                                             #
# ---------------------------------------------------------------------- #


class TestIdUniqueness:
    def test_duplicate_axis_id_rejected(self) -> None:
        payload = _minimal_payload()
        payload["axes"].append({"id": "x", "steppers": []})
        with pytest.raises(ValueError, match="Duplicate id 'x'"):
            model_validate(payload)

    def test_duplicate_stepper_id_rejected(self) -> None:
        payload = _minimal_payload()
        payload["steppers"].append(dict(payload["steppers"][0]))
        with pytest.raises(ValueError, match="Duplicate id 'stepper_x'"):
            model_validate(payload)

    def test_duplicate_endstop_id_rejected(self) -> None:
        payload = _minimal_payload()
        payload["endstops"].extend(
            [
                {"id": "endstop_x_min", "pin": "^PC0"},
                {"id": "endstop_x_min", "pin": "^PC1"},
            ]
        )
        with pytest.raises(ValueError, match="Duplicate id 'endstop_x_min'"):
            model_validate(payload)

    def test_duplicate_in_temperature_sensors_rejected(self) -> None:
        payload = _minimal_payload()
        payload["temperature_sensors"].extend(
            [
                {"id": "sensor_extruder", "pin": "PA1"},
                {"id": "sensor_extruder", "pin": "PA2"},
            ]
        )
        with pytest.raises(ValueError, match="Duplicate id 'sensor_extruder'"):
            model_validate(payload)

    def test_same_id_in_different_lists_is_allowed(self) -> None:
        """The id namespace is per-list. ``stepper_x`` and
        ``tool_x`` may coexist because they're in different
        top-level lists — the list name is the type discriminator.
        """
        payload = _minimal_payload()
        payload["tools"].append(
            {
                "id": "x",
                "type": "extruder",
                "heater_pin": "PE3",
                "control": "pid",
                "sensor": "x",
            }
        )
        payload["temperature_sensors"].append(
            {"id": "x", "pin": "PA1"}
        )
        model = model_validate(payload)
        assert model.tools[0].id == "x"
        assert model.temperature_sensors[0].id == "x"


# ---------------------------------------------------------------------- #
# ID pattern                                                                #
# ---------------------------------------------------------------------- #


class TestIdPattern:
    @pytest.mark.parametrize(
        "entity_key",
        ["axes", "steppers", "drivers", "endstops", "tools", "temperature_sensors", "fans"],
    )
    def test_id_must_be_lowercase_snake(self, entity_key: str) -> None:
        payload = _minimal_payload()
        if entity_key == "axes":
            payload["axes"].append({"id": "X", "steppers": []})
        elif entity_key == "steppers":
            payload["steppers"].append(dict(payload["steppers"][0], id="Stepper-X"))
        elif entity_key == "drivers":
            payload["drivers"].append({"id": "Driver-X", "type": "TMC2209"})
        elif entity_key == "endstops":
            payload["endstops"].append({"id": "Endstop-X", "pin": "^PC0"})
        elif entity_key == "tools":
            payload["tools"].append(
                {
                    "id": "Tool-X",
                    "type": "extruder",
                    "heater_pin": "PE3",
                    "control": "pid",
                }
            )
        elif entity_key == "temperature_sensors":
            payload["temperature_sensors"].append({"id": "Sensor-X", "pin": "PA1"})
        elif entity_key == "fans":
            payload["fans"].append({"id": "Fan-X", "pin": "PC8"})

        with pytest.raises(ValueError, match="String should match pattern"):
            model_validate(payload)


# ---------------------------------------------------------------------- #
# Cross-reference resolution                                                #
# ---------------------------------------------------------------------- #


class TestCrossReferences:
    def test_axis_stepper_reference_must_resolve(self) -> None:
        payload = _minimal_payload()
        payload["axes"][0]["steppers"].append("unknown_stepper")
        with pytest.raises(ValueError, match="references unknown stepper 'unknown_stepper'"):
            model_validate(payload)

    def test_axis_endstop_reference_must_resolve(self) -> None:
        """``axis.endstop`` is a string id; it must point at a top-level record."""
        payload = _minimal_payload()
        payload["axes"][0]["endstop"] = "endstop_x_min"
        with pytest.raises(ValueError, match="references unknown endstop"):
            model_validate(payload)

    def test_axis_endstop_pin_does_not_require_record(self) -> None:
        """``axis.endstop_pin`` is the inline Klipper form. No matching
        top-level endstop entity is required — the pin stands on its own.
        """
        payload = _minimal_payload()
        payload["axes"][0]["endstop_pin"] = "PG6"
        model = model_validate(payload)
        assert model.axes[0].endstop_pin == "PG6"
        assert model.endstops == []

    def test_stepper_driver_reference_must_resolve(self) -> None:
        payload = _minimal_payload()
        payload["steppers"][0]["driver"] = "unknown_driver"
        with pytest.raises(ValueError, match="references unknown driver 'unknown_driver'"):
            model_validate(payload)

    def test_tool_sensor_reference_must_resolve_to_temperature_sensor(self) -> None:
        """A tool referencing a non-existent temperature sensor fails."""

        payload = _minimal_payload()
        payload["tools"].append(
            {
                "id": "heater_extruder",
                "type": "extruder",
                "heater_pin": "PE3",
                "control": "pid",
                "sensor": "missing_sensor",
            }
        )
        with pytest.raises(ValueError, match="references unknown temperature sensor"):
            model_validate(payload)

    def test_tool_sensor_reference_does_not_satisfy_via_pressure_sensors(self) -> None:
        """The validator must look up ``tool.sensor`` only in
        ``temperature_sensors``, not in any future ``pressure_sensors``
        list. This tests the discriminator property: id collision
        across lists is allowed, but a wrong-list reference is
        rejected.
        """
        payload = _minimal_payload()
        payload["tools"].append(
            {
                "id": "heater_extruder",
                "type": "extruder",
                "heater_pin": "PE3",
                "control": "pid",
                "sensor": "pressure_extruder",
            }
        )
        with pytest.raises(ValueError, match="references unknown temperature sensor"):
            model_validate(payload)

    def test_tool_fan_reference_must_resolve(self) -> None:
        payload = _minimal_payload()
        payload["tools"].append(
            {
                "id": "heater_extruder",
                "type": "extruder",
                "heater_pin": "PE3",
                "control": "pid",
                "fan": "missing_fan",
            }
        )
        with pytest.raises(ValueError, match="references unknown fan"):
            model_validate(payload)

    def test_standalone_fan_record_is_accepted(self) -> None:
        """A ``[fan]``-derived Fan record (``max_power`` optional) round-trips."""
        payload = _minimal_payload()
        payload["fans"].append(
            {"id": "fan_part_cooling", "pin": "PA8", "max_power": 0.5}
        )
        model = model_validate(payload)
        assert any(f.id == "fan_part_cooling" for f in model.fans)

    def test_fan_records_must_have_unique_ids(self) -> None:
        """Two Fan records sharing an id are rejected (graph-level validator)."""
        payload = _minimal_payload()
        payload["fans"].append({"id": "fan_dup", "pin": "PA8"})
        payload["fans"].append({"id": "fan_dup", "pin": "PB0"})
        with pytest.raises(ValueError, match="Duplicate id 'fan_dup'"):
            model_validate(payload)

    def test_one_endstop_record_per_switch(self) -> None:
        """Each Klipper ``[endstop_switch NAME]`` produces ONE record."""
        payload = _minimal_payload()
        payload["endstops"].append({"id": "endstop_x_min", "pin": "^PC0"})
        model = model_validate(payload)
        assert len(model.endstops) == 1
        assert model.endstops[0].pin == "^PC0"


# ---------------------------------------------------------------------- #
# Axis.endstop exclusivity                                                 #
# ---------------------------------------------------------------------- #


class TestAxisEndstopExclusivity:
    """Either ``endstop`` or ``endstop_pin`` may be set on an axis, never both."""

    def test_endstop_only(self) -> None:
        payload = _minimal_payload()
        payload["endstops"].append({"id": "endstop_x_min", "pin": "PG6"})
        payload["axes"][0]["endstop"] = "endstop_x_min"
        model = model_validate(payload)
        assert model.axes[0].endstop == "endstop_x_min"
        assert model.axes[0].endstop_pin is None

    def test_endstop_pin_only(self) -> None:
        payload = _minimal_payload()
        payload["axes"][0]["endstop_pin"] = "PG6"
        model = model_validate(payload)
        assert model.axes[0].endstop_pin == "PG6"
        assert model.axes[0].endstop is None

    def test_neither_field_set_is_allowed(self) -> None:
        """An axis with no endstop at all (e.g. extruder joints) is valid."""
        payload = _minimal_payload()
        model = model_validate(payload)
        assert model.axes[0].endstop is None
        assert model.axes[0].endstop_pin is None

    def test_both_endstop_and_endstop_pin_rejected(self) -> None:
        payload = _minimal_payload()
        payload["endstops"].append({"id": "endstop_x_min", "pin": "PG6"})
        payload["axes"][0]["endstop"] = "endstop_x_min"
        payload["axes"][0]["endstop_pin"] = "PG6"
        with pytest.raises(ValueError, match="sets both 'endstop' and 'endstop_pin'"):
            model_validate(payload)


# ---------------------------------------------------------------------- #
# Endstop multi-axis reuse                                                  #
# ---------------------------------------------------------------------- #


class TestEndstopMultiAxis:
    """One Endstop entity may be referenced by multiple axes."""

    def test_two_axes_share_same_endstop(self) -> None:
        payload = _minimal_payload()
        payload["endstops"].append({"id": "endstop_x_min", "pin": "PG6"})
        payload["axes"].append(
            {"id": "z", "steppers": [], "endstop": "endstop_x_min"}
        )
        model = model_validate(payload)
        endstop_refs = {a.endstop for a in model.axes if a.endstop}
        assert endstop_refs == {"endstop_x_min"}


# ---------------------------------------------------------------------- #
# Axis.pos                                                                  #
# ---------------------------------------------------------------------- #


class TestAxisPos:
    def test_pos_optional(self) -> None:
        payload = _minimal_payload()
        model = model_validate(payload)
        assert model.axes[0].pos is None

    def test_pos_stored_on_axis(self) -> None:
        payload = _minimal_payload()
        payload["endstops"].append({"id": "endstop_x_min", "pin": "PG6"})
        payload["axes"][0]["endstop"] = "endstop_x_min"
        payload["axes"][0]["pos"] = 5.5
        model = model_validate(payload)
        assert model.axes[0].pos == 5.5


# ---------------------------------------------------------------------- #
# Endstop entity shape                                                     #
# ---------------------------------------------------------------------- #


class TestEndstopShape:
    """Top-level Endstop records are stripped to ``{id, pin}``."""

    def test_endstop_accepts_only_id_and_pin(self) -> None:
        payload = _minimal_payload()
        payload["endstops"].append({"id": "endstop_x_min", "pin": "PG6"})
        model = model_validate(payload)
        assert model.endstops[0].id == "endstop_x_min"
        assert model.endstops[0].pin == "PG6"

    def test_endstop_rejects_legacy_type_field(self) -> None:
        """``type`` was the previous behaviour discriminator; the new
        schema forbids it so a stale payload fails loudly.
        """
        payload = _minimal_payload()
        payload["endstops"].append(
            {"id": "endstop_x_min", "pin": "PG6", "type": "Home"}
        )
        with pytest.raises(ValueError, match="type"):
            model_validate(payload)

    def test_endstop_rejects_legacy_pos_field(self) -> None:
        """``pos`` moved onto Axis; a top-level Endstop carrying it fails."""
        payload = _minimal_payload()
        payload["endstops"].append(
            {"id": "endstop_x_min", "pin": "PG6", "pos": 0.0}
        )
        with pytest.raises(ValueError, match="pos"):
            model_validate(payload)

    def test_endstop_rejects_legacy_stepper_field(self) -> None:
        """The previous ``stepper`` back-reference is gone (one endstop
        can be used by multiple axes, so a single owner is no longer
        well-defined)."""
        payload = _minimal_payload()
        payload["endstops"].append(
            {
                "id": "endstop_x_min",
                "pin": "PG6",
                "stepper": "stepper_x",
            }
        )
        with pytest.raises(ValueError, match="stepper"):
            model_validate(payload)


# ---------------------------------------------------------------------- #
# Multi-error aggregation                                                  #
# ---------------------------------------------------------------------- #


class TestErrorAggregation:
    def test_multiple_errors_reported_in_one_pass(self) -> None:
        """A single ``ValueError`` lists every problem so the
        consumer doesn't fix them one at a time.
        """
        payload = _minimal_payload()
        payload["axes"].append({"id": "y", "steppers": ["stepper_x"]})
        payload["axes"][0]["endstop"] = "missing_endstop"
        payload["steppers"].append(dict(payload["steppers"][0]))
        with pytest.raises(ValueError) as exc_info:
            model_validate(payload)
        message = str(exc_info.value)
        assert "Duplicate id 'stepper_x'" in message
        assert "references unknown endstop 'missing_endstop'" in message
        assert message.count(" - ") >= 2
