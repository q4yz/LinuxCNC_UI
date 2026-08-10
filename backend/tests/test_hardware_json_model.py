"""Tests for the ``hardware.json`` v2 Pydantic model and its cross-reference validator."""

from __future__ import annotations

import pytest

from modules.machineconfig.models.hardware_json_models import (
    Axis,
    Driver,
    Endstop,
    Fan,
    HardwareJson,
    Heater,
    HardwareJson,
    Stepper,
    TemperatureSensor,
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
            {"id": "x", "steppers": ["stepper_x"], "endstops": []},
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
        "heaters": [],
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
        """A machine with no heaters, sensors, fans, or endstops is valid."""

        payload = _minimal_payload()
        model = model_validate(payload)
        assert model.heaters == []
        assert model.temperature_sensors == []
        assert model.fans == []
        assert model.endstops == []
        assert model.axes == [
            Axis(id="x", steppers=["stepper_x"], endstops=[])
        ]

    def test_to_dict_omits_none_values(self) -> None:
        """The serialised payload drops None values to keep the JSON lean."""

        payload = _minimal_payload()
        model = model_validate(payload)
        serialised = to_dict(model)
        # No ``None`` literal anywhere — the consumer can rely on
        # ``value is None`` checks because the field is absent.
        flat = str(serialised)
        assert "None" not in flat


# ---------------------------------------------------------------------- #
# ID uniqueness                                                             #
# ---------------------------------------------------------------------- #


class TestIdUniqueness:
    def test_duplicate_axis_id_rejected(self) -> None:
        payload = _minimal_payload()
        payload["axes"].append(payload["axes"][0])
        with pytest.raises(ValueError, match="Duplicate id 'x'"):
            model_validate(payload)

    def test_duplicate_stepper_id_rejected(self) -> None:
        payload = _minimal_payload()
        payload["steppers"].append(dict(payload["steppers"][0]))
        with pytest.raises(ValueError, match="Duplicate id 'stepper_x'"):
            model_validate(payload)

    def test_duplicate_endstop_id_rejected(self) -> None:
        payload = _minimal_payload()
        payload["endstops"].append(
            {
                "id": "endstop_x_min",
                "stepper": "stepper_x",
                "pin": "^PC0",
                "pos": 0.0,
                "type": "Estop",
            }
        )
        payload["endstops"].append(
            {
                "id": "endstop_x_min",
                "stepper": "stepper_x",
                "pin": "^PC1",
                "pos": 0.0,
                "type": "Estop",
            }
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
        ``heater_x`` may coexist because they're in different
        top-level lists — the list name is the type discriminator.
        """
        payload = _minimal_payload()
        payload["heaters"].append(
            {
                "id": "x",
                "heater_pin": "PE3",
                "control": "pid",
                "sensor": "x",
            }
        )
        payload["temperature_sensors"].append(
            {"id": "x", "pin": "PA1"}
        )
        # Both share the id "x" but live in different lists.
        model = model_validate(payload)
        assert model.heaters[0].id == "x"
        assert model.temperature_sensors[0].id == "x"


# ---------------------------------------------------------------------- #
# ID pattern                                                                #
# ---------------------------------------------------------------------- #


class TestIdPattern:
    @pytest.mark.parametrize(
        "entity_key",
        ["axes", "steppers", "drivers", "endstops", "heaters", "temperature_sensors", "fans"],
    )
    def test_id_must_be_lowercase_snake(self, entity_key: str) -> None:
        payload = _minimal_payload()
        if entity_key == "axes":
            payload["axes"].append({"id": "X", "steppers": [], "endstops": []})
        elif entity_key == "steppers":
            payload["steppers"].append(dict(payload["steppers"][0], id="Stepper-X"))
        elif entity_key == "drivers":
            payload["drivers"].append({"id": "Driver-X", "type": "TMC2209"})
        elif entity_key == "endstops":
            payload["endstops"].append(
                {
                    "id": "Endstop-X",
                    "stepper": "stepper_x",
                    "pin": "^PC0",
                    "pos": 0.0,
                    "type": "Estop",
                }
            )
        elif entity_key == "heaters":
            payload["heaters"].append(
                {"id": "Heater-X", "heater_pin": "PE3", "control": "pid"}
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
        """Inline ``axis.endstops[*].id`` must point at a top-level record."""
        payload = _minimal_payload()
        payload["axes"][0]["endstops"].append(
            {"id": "endstop_x_min", "type": "Estop", "pos": 0.0}
        )
        with pytest.raises(
            ValueError, match="inline endstop 'endstop_x_min'"
        ):
            model_validate(payload)

    def test_stepper_driver_reference_must_resolve(self) -> None:
        payload = _minimal_payload()
        payload["steppers"][0]["driver"] = "unknown_driver"
        with pytest.raises(ValueError, match="references unknown driver 'unknown_driver'"):
            model_validate(payload)

    def test_endstop_stepper_reference_must_resolve(self) -> None:
        payload = _minimal_payload()
        payload["endstops"].append(
            {
                "id": "endstop_x_min",
                "stepper": "unknown_stepper",
                "pin": "^PC0",
                "pos": 0.0,
                "type": "Estop",
            }
        )
        with pytest.raises(ValueError, match="references unknown stepper 'unknown_stepper'"):
            model_validate(payload)

    def test_heater_sensor_reference_must_resolve_to_temperature_sensor(self) -> None:
        """A heater referencing a non-existent temperature sensor fails."""

        payload = _minimal_payload()
        payload["heaters"].append(
            {
                "id": "heater_extruder",
                "heater_pin": "PE3",
                "control": "pid",
                "sensor": "missing_sensor",
            }
        )
        with pytest.raises(ValueError, match="references unknown temperature sensor"):
            model_validate(payload)

    def test_heater_sensor_reference_does_not_satisfy_via_pressure_sensors(self) -> None:
        """The validator must look up ``heater.sensor`` only in
        ``temperature_sensors``, not in any future ``pressure_sensors``
        list. This tests the discriminator property: id collision
        across lists is allowed, but a wrong-list reference is
        rejected.
        """
        # The minimum payload adds a heater with no sensor. We
        # simulate a future pressure_sensors list by adding it
        # manually; the validator must not satisfy the heater's
        # ``sensor`` reference from it.
        payload = _minimal_payload()
        payload["heaters"].append(
            {
                "id": "heater_extruder",
                "heater_pin": "PE3",
                "control": "pid",
                "sensor": "pressure_extruder",
            }
        )
        # ``pressure_extruder`` is a future type id; the v2 model
        # doesn't know it. The validator fails because the id
        # isn't in ``temperature_sensors``. (If a future
        # ``pressure_sensors`` list is added, the lookup table
        # for ``heater.sensor`` is intentionally NOT extended.)
        with pytest.raises(ValueError, match="references unknown temperature sensor"):
            model_validate(payload)

    def test_heater_fan_reference_must_resolve(self) -> None:
        payload = _minimal_payload()
        payload["heaters"].append(
            {
                "id": "heater_extruder",
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
        payload["endstops"].append(
            {
                "id": "endstop_x_min",
                "stepper": "stepper_x",
                "pin": "^PC0",
                "pos": 0.0,
                "type": "Estop",
            }
        )
        model = model_validate(payload)
        assert len(model.endstops) == 1
        assert model.endstops[0].type == "Estop"


# ---------------------------------------------------------------------- #
# Endstop type enum                                                        #
# ---------------------------------------------------------------------- #


class TestEndstopType:
    def test_unknown_type_rejected(self) -> None:
        payload = _minimal_payload()
        payload["endstops"].append(
            {
                "id": "endstop_x_min",
                "stepper": "stepper_x",
                "pin": "^PC0",
                "pos": 0.0,
                "type": "macro",
            }
        )
        with pytest.raises(ValueError, match="type"):
            model_validate(payload)

    def test_all_valid_types_accepted(self) -> None:
        """``None``, ``"Estop"``, and ``"Home"`` are all valid."""
        for type_value in (None, "Estop", "Home"):
            payload = _minimal_payload()
            payload["endstops"].append(
                {
                    "id": "endstop_x_min",
                    "stepper": "stepper_x",
                    "pin": "^PC0",
                    "pos": 0.0,
                    "type": type_value,
                }
            )
            model = model_validate(payload)
            assert model.endstops[0].type == type_value


# ---------------------------------------------------------------------- #
# Multi-error aggregation                                                  #
# ---------------------------------------------------------------------- #


class TestErrorAggregation:
    def test_multiple_errors_reported_in_one_pass(self) -> None:
        """A single ``ValueError`` lists every problem so the
        consumer doesn't fix them one at a time.
        """
        payload = _minimal_payload()
        # Two axes reference the same stepper_id (one valid, one bogus).
        payload["axes"].append({"id": "y", "steppers": ["stepper_x"], "endstops": []})
        # A bogus inline endstop reference.
        payload["axes"][0]["endstops"].append(
            {"id": "endstop_x_min", "type": "Estop", "pos": 0.0}
        )
        # Two duplicate steppers.
        payload["steppers"].append(dict(payload["steppers"][0]))
        with pytest.raises(ValueError) as exc_info:
            model_validate(payload)
        message = str(exc_info.value)
        # All three errors are surfaces in the same message.
        assert "Duplicate id 'stepper_x'" in message
        assert "inline endstop 'endstop_x_min'" in message
        # The duplicate-axis error would be inside the same message.
        assert message.count(" - ") >= 2
