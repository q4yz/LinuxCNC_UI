"""Tests for the ``hardware.json`` v2 Pydantic model and its cross-reference validator."""

from __future__ import annotations
from tests._module_app_factory import build_module_app

import pytest

from models.machineconfig.hardware_json_models import (
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
    """A minimal but valid ``hardware.json`` v2.1 payload.

    Every entity is present with the bare minimum fields the model
    requires. Tests mutate this dict to add or break fields.
    """
    return {
        "version": "2.1",
        "machine": "test",
        "source": "KlipperToLinuxCNCCompiler",
        "kinematics": "cartesian",
        "hal_type": "remora",
        "axes": [
            {"id": "x", "joint_numbers": [0]},
        ],
        "joints": [
            {
                "id": "stepper_x",
                "joint_number": 0,
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
    def test_version_must_be_2_1(self) -> None:
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
        assert model.axes == [Axis(id="x", joint_numbers=[0])]

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
    def test_duplicate_joint_id_rejected(self) -> None:
        payload = _minimal_payload()
        payload["joints"].append(dict(payload["joints"][0]))
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
    """Every entity that carries an ``id`` field must match the
    lowercase-snake pattern. The parametrize set covers every list
    including ``axes`` (axes are now identified by string ``id``).
    """

    @pytest.mark.parametrize(
        "entity_key",
        ["axes", "joints", "drivers", "endstops", "tools", "temperature_sensors", "fans"],
    )
    def test_id_must_be_lowercase_snake(self, entity_key: str) -> None:
        payload = _minimal_payload()
        if entity_key == "axes":
            payload["axes"].append({"id": "Axis-X", "joint_numbers": []})
        elif entity_key == "joints":
            payload["joints"].append(dict(payload["joints"][0], id="Stepper-X"))
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
    def test_axis_joint_numbers_reference_must_resolve(self) -> None:
        """``axis.joint_numbers`` is a ``list[int]``; each integer
        must match a ``joint_number`` in the top-level ``joints[]``
        list. Unknown joint_numbers are rejected.
        """
        payload = _minimal_payload()
        payload["axes"][0]["joint_numbers"].append(999)
        with pytest.raises(
            ValueError, match="references unknown joint_number '999'"
        ):
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

    def test_joint_driver_reference_must_resolve(self) -> None:
        payload = _minimal_payload()
        payload["joints"][0]["driver"] = "unknown_driver"
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
        # Second axis: no joints, but reuses the existing endstop.
        # Use ``id="u"`` (a letter not already used) and an empty
        # ``joint_numbers`` list (an axis with no joints is allowed).
        payload["axes"].append(
            {
                "id": "u",
                "joint_numbers": [],
                "endstop": "endstop_x_min",
            }
        )
        model = model_validate(payload)
        endstop_refs = {a.endstop for a in model.axes if a.endstop}
        assert endstop_refs == {"endstop_x_min"}


# ---------------------------------------------------------------------- #
# Axis.position_endstop / Axis.position_max                                #
# ---------------------------------------------------------------------- #


class TestAxisMotionFields:
    def test_position_endstop_optional(self) -> None:
        payload = _minimal_payload()
        model = model_validate(payload)
        assert model.axes[0].position_endstop is None
        assert model.axes[0].position_max is None

    def test_position_endstop_stored_on_axis(self) -> None:
        payload = _minimal_payload()
        payload["endstops"].append({"id": "endstop_x_min", "pin": "PG6"})
        payload["axes"][0]["endstop"] = "endstop_x_min"
        payload["axes"][0]["position_endstop"] = 5.5
        model = model_validate(payload)
        assert model.axes[0].position_endstop == 5.5

    def test_position_max_stored_on_axis(self) -> None:
        payload = _minimal_payload()
        payload["axes"][0]["position_max"] = 250.0
        model = model_validate(payload)
        assert model.axes[0].position_max == 250.0

    def test_motion_fields_not_on_joint(self) -> None:
        """``position_max`` / ``position_endstop`` are forbidden on
        the joint record — they belong on the axis.
        """
        payload = _minimal_payload()
        payload["joints"][0]["position_max"] = 300.0
        with pytest.raises(ValueError, match="position_max"):
            model_validate(payload)


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
# joint_number                                                              #
# ---------------------------------------------------------------------- #


class TestJointNumber:
    """``joint_number`` is the LinuxCNC ``[JOINT_N]`` index.

    Required on every joint entry, must be non-negative, and must
    be unique across the ``joints[]`` list (the runtime maps it
    to a Remora stepgen channel ``remora.joint.{N}.*`` — two
    joints sharing a number would collide).
    """

    def test_joint_number_required(self) -> None:
        payload = _minimal_payload()
        del payload["joints"][0]["joint_number"]
        with pytest.raises(ValueError, match="joint_number"):
            model_validate(payload)

    def test_joint_number_must_be_non_negative(self) -> None:
        payload = _minimal_payload()
        payload["joints"][0]["joint_number"] = -1
        with pytest.raises(ValueError, match="joint_number"):
            model_validate(payload)

    def test_duplicate_joint_number_rejected(self) -> None:
        """Two joints sharing a ``joint_number`` collide on the
        Remora stepgen channel; the cross-ref validator rejects
        the payload.
        """
        payload = _minimal_payload()
        payload["axes"].append({"id": "y", "joint_numbers": [1]})
        payload["joints"].append(
            dict(payload["joints"][0], id="stepper_y", joint_number=0)
        )
        with pytest.raises(ValueError, match="Duplicate joint_number '0'"):
            model_validate(payload)


# ---------------------------------------------------------------------- #
# Axis identification                                                       #
# ---------------------------------------------------------------------- #


class TestAxisId:
    """Axis identification: string ``id`` (canonical LinuxCNC letter)
    plus ``joint_numbers`` listing every driving joint. ``id`` must
    match the lowercase id pattern and must be unique across the
    ``axes[]`` list — two axes sharing an id would either collide on
    the ``[AXIS_*]`` INI section or render with the same runtime
    handle.
    """

    def test_id_is_required(self) -> None:
        payload = _minimal_payload()
        del payload["axes"][0]["id"]
        with pytest.raises(ValueError, match="id"):
            model_validate(payload)

    def test_id_must_match_pattern(self) -> None:
        payload = _minimal_payload()
        payload["axes"][0]["id"] = "X"  # uppercase rejected
        with pytest.raises(ValueError, match="id"):
            model_validate(payload)

    def test_duplicate_axis_id_rejected(self) -> None:
        """Two axes sharing an id collide on the ``[AXIS_*]`` INI
        block and on the runtime snapshot dict key.
        """
        payload = _minimal_payload()
        payload["axes"].append({"id": "x", "joint_numbers": [0]})
        with pytest.raises(ValueError, match="Duplicate id 'x'"):
            model_validate(payload)

    def test_multi_motor_axis_is_valid(self) -> None:
        """A dual-motor axis lists multiple joint_numbers under one
        string id.
        """
        payload = _minimal_payload()
        payload["joints"].append(
            dict(payload["joints"][0], id="stepper_y", joint_number=1)
        )
        payload["axes"][0] = {"id": "x", "joint_numbers": [0, 1]}
        model = model_validate(payload)
        assert model.axes[0].id == "x"
        assert model.axes[0].joint_numbers == [0, 1]


# ---------------------------------------------------------------------- #
# Multi-error aggregation                                                  #
# ---------------------------------------------------------------------- #


class TestErrorAggregation:
    def test_multiple_errors_reported_in_one_pass(self) -> None:
        """A single ``ValueError`` lists every problem so the
        consumer doesn't fix them one at a time.
        """
        payload = _minimal_payload()
        # Append an axis that references a duplicate joint id and
        # an endstop that doesn't exist. The first ``axes[0]``
        # also picks up a stale endstop reference so the
        # aggregation has at least two distinct error messages.
        payload["axes"].append(
            {"id": "y", "joint_numbers": [1]}
        )
        payload["axes"][0]["endstop"] = "missing_endstop"
        payload["joints"].append(dict(payload["joints"][0]))
        with pytest.raises(ValueError) as exc_info:
            model_validate(payload)
        message = str(exc_info.value)
        assert "Duplicate id 'stepper_x'" in message
        assert "references unknown endstop 'missing_endstop'" in message
        assert message.count(" - ") >= 2
