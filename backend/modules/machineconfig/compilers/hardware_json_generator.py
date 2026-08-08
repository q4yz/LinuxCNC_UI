"""Generate ``hardware.json`` — the backend's high-level hardware overview.

``hardware.json`` is the canonical record of every pin, stepper,
driver, heater, sensor, endstop, and fan the backend knows about.
It is derived from the parsed Klipper graph at compile time and
consumed by everything that needs to query the hardware
(deployment tools, the console, future Remora firmware flasher)
without parsing the raw config again.

Shape
-----
The payload is the ``hardware.json`` v2 model — see
:mod:`backend.modules.machineconfig.models.hardware_json_models`.
The model is flat with explicit ``id`` fields and string
references; the cross-reference validator walks the graph in one
pass to enforce every reference resolves into the right list.

IDs are auto-assigned from the Klipper section name. ``[stepper_x]``
becomes ``id: "stepper_x"``; ``[heater_bed]`` becomes
``id: "heater_bed"``. The same convention applies to switches —
``[endstop_switch X_MIN]`` produces three records (one per role)
with the same ``endstop_id`` (``"X_MIN"``) and distinct record ids.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..models import MachineConfigGraph
from ..models.hardware_json_models import (
    HardwareJson as _HardwareJsonModel,
    to_dict as _model_to_dict,
)
from .axis_builder import AxisBuilder, stepgen_scale

logger = logging.getLogger("backend.modules.machineconfig.compilers.hardware_json_generator")


# ---------------------------------------------------------------------- #
# ID derivation                                                           #
# ---------------------------------------------------------------------- #


def _axis_id(graph: MachineConfigGraph, letter: str) -> str:
    """Canonical id for an axis entry.

    The id is the lower-case axis letter from the stepper section
    header (``[stepper_x]`` -> ``x``). Multi-motor axes that share
    a letter keep the same id so the axes list stays unique.
    """
    return letter.lower()


def _stepper_id(section_name: str) -> str:
    """Canonical id for a stepper entry.

    Derived from the Klipper section name. ``[stepper_x]`` ->
    ``stepper_x``; ``[stepper_x1]`` -> ``stepper_x1``; named
    extruders ``[extruder hotend]`` use the heater id so the
    cross-reference from the heater to its stepper is implicit.
    """
    return section_name


def _driver_id(graph: MachineConfigGraph, stepper_section: str) -> str:
    """Canonical id for a driver entry.

    The driver id is ``driver_<stepper_id>`` so a one-to-one
    relationship holds by default. Profiles with shared drivers
    (rare) can override later via a separate id policy.
    """
    return f"driver_{stepper_section}"


def _endstop_id(endstop_section: str, role: str) -> str:
    """Canonical id for an endstop record.

    The same Klipper ``[endstop_switch NAME]`` section produces
    three records (one per role). The id is
    ``endstop_<NAME>_<role>`` for the ``endstop`` role,
    ``homing_<NAME>`` for the homing role, and
    ``macros_<NAME>`` for the ignore role — three distinct records
    sharing the same ``endstop_id`` (the Klipper switch name).
    """
    if role == "endstop":
        return f"endstop_{endstop_section}"
    if role == "homing":
        return f"homing_{endstop_section}"
    return f"macros_{endstop_section}"


def _heater_id(heater_section: str) -> str:
    """Canonical id for a heater entry.

    ``[heater_bed]`` -> ``heater_bed``; ``[heater_generic chamber]``
    -> ``heater_generic_chamber``; ``[extruder]`` -> ``heater_extruder``
    so the canonical id is uniform across all heater shapes.
    """
    if heater_section == "extruder":
        return "heater_extruder"
    if heater_section.startswith("heater_"):
        return heater_section
    return f"heater_{heater_section}"


def _temperature_sensor_id(heater_section: str) -> str:
    """Canonical id for a temperature sensor.

    Temperature sensors today are auto-discovered from the
    ``heater_pin``/``sensor_pin`` fields of heater-shaped sections,
    so the id matches the heater's id (minus the ``heater_`` prefix
    to keep the type-agnostic ``id`` namespace uniform across the
    heater, sensor, and fan derived from the same source section).
    """
    if heater_section == "extruder":
        return "extruder"
    if heater_section.startswith("heater_"):
        return heater_section[len("heater_"):]
    return heater_section


def _fan_id(heater_section: str) -> str:
    """Canonical id for a fan entry.

    Driven by the ``fan`` field on a heater; the id is the
    ``fan_<heater_section>`` convention so the same fan is
    addressable by the same handle whether it's referenced from a
    heater or a future standalone controller.
    """
    if heater_section == "extruder":
        return "fan_extruder"
    if heater_section.startswith("heater_"):
        return f"fan_{heater_section}"
    return f"fan_heater_{heater_section}"


# ---------------------------------------------------------------------- #
# Endstop helper                                                          #
# ---------------------------------------------------------------------- #


def _endstop_records(
    endstop_section: str,
    klipper_switch_name: str,
    stepper_id: str,
    pin: str,
    pos: float | None,
) -> list[dict[str, Any]]:
    """Three records per Klipper ``[endstop_switch NAME]`` section.

    The Klipper convention is one switch per section. The
    hardware.json v2 model lifts the switch into the record itself
    (``endstop_id``) and emits three records per switch — one
    per role — so downstream consumers can bind a switch to each
    purpose without re-deriving the role from other state.

    ``position_endstop`` is optional on the Klipper source; the
    ``pos`` field defaults to ``0.0`` when absent.
    """
    pos_value = pos if pos is not None else 0.0
    base = {
        "endstop_id": klipper_switch_name,
        "stepper": stepper_id,
        "pin": pin,
        "pos": pos_value,
    }
    return [
        {**base, "id": _endstop_id(endstop_section, "endstop"), "type": "endstop"},
        {**base, "id": _endstop_id(endstop_section, "homing"), "type": "homing"},
        {**base, "id": _endstop_id(endstop_section, "ignore"), "type": "ignore"},
    ]


# ---------------------------------------------------------------------- #
# Heater payload                                                          #
# ---------------------------------------------------------------------- #


def _heater_payload(heater_section: str, h) -> dict[str, Any]:
    """Build a heater entry's payload dict.

    The id is the canonical heater id from :func:`_heater_id`. The
    ``sensor`` and ``fan`` references are string ids that the
    cross-reference validator resolves into ``temperature_sensors``
    and ``fans`` respectively.
    """
    return {
        "id": _heater_id(heater_section),
        "sensor": _temperature_sensor_id(heater_section),
        "heater_pin": h.heater_pin,
        "control": h.control,
        "min_temp": h.min_temp,
        "max_temp": h.max_temp,
    }


def _temperature_sensor_payload(heater_section: str, h) -> dict[str, Any]:
    """Build a temperature sensor entry from the heater's sensor_pin + sensor_type."""

    return {
        "id": _temperature_sensor_id(heater_section),
        "pin": h.sensor_pin,
        "type": h.sensor_type,
    }


def _fan_payload(heater_section: str, h) -> dict[str, Any]:
    """Build a fan entry from a heater's heater_pin.

    The fan id is conventional (``fan_<heater_id>``). Profiles with
    a dedicated ``[fan]`` Klipper section are not yet part of the
    Klipper → hardware.json pipeline; when they are, the canonical
    id policy will be extended.
    """
    return {
        "id": _fan_id(heater_section),
        "pin": h.heater_pin,
    }


# ---------------------------------------------------------------------- #
# Stepper payload                                                         #
# ---------------------------------------------------------------------- #


def _stepper_payload(stepper_section: str, stepper) -> dict[str, Any]:
    """Build a stepper entry's payload dict.

    Derived fields (``scale``, ``joint_number``) are not stored —
    they're computed at consumer time. The driver id is
    ``driver_<stepper_id>`` so a one-to-one relationship holds by
    default.
    """
    return {
        "id": _stepper_id(stepper_section),
        "driver": _driver_id(None, stepper_section),
        "step_pin": stepper.step_pin,
        "dir_pin": stepper.dir_pin,
        "enable_pin": stepper.enable_pin,
        "microsteps": stepper.microsteps,
        "rotation_distance": _fmt_float(stepper.rotation_distance),
        "position_min": _fmt_float(getattr(stepper, "position_min", None)),
        "position_max": _fmt_float(stepper.position_max),
        "position_endstop": _fmt_float(stepper.position_endstop),
        "homing_speed": _fmt_float(getattr(stepper, "homing_speed", None)),
    }


def _fmt_float(value: float | None) -> float | None:
    """Format a float, returning None for missing values."""
    if value is None:
        return None
    return round(float(value), 4)


# ---------------------------------------------------------------------- #
# Driver payload                                                          #
# ---------------------------------------------------------------------- #


def _driver_payload(driver_id: str, stepper) -> dict[str, Any]:
    """Build a driver entry.

    A driver is the chip-level wiring (TMC2209, etc.). The runtime
    driver settings live in the parser output (``graph.tmc2209s``)
    and are looked up by the stepper this driver drives. Future
    parser support for other driver types will extend this helper.
    """
    return {
        "id": driver_id,
        "type": "TMC2209",
        "uart_pin": None,
        "run_current": None,
        "microsteps": None,
        "stealthchop_threshold": None,
        "interpolate": None,
        "hold_current": None,
        "sense_resistor": None,
    }


# ---------------------------------------------------------------------- #
# Axis payload                                                            #
# ---------------------------------------------------------------------- #


def _axis_payload(letter: str, stepper_ids: list[str], endstop_ids: list[str]) -> dict[str, Any]:
    """Build an axis entry.

    The axis id is the lower-case letter of the canonical stepper it
    owns. Multi-motor axes share the id so the axes list stays
    unique; the underlying steppers are still listed individually.
    """
    return {
        "id": _axis_id(None, letter),
        "steppers": stepper_ids,
        "endstops": endstop_ids,
    }


# ---------------------------------------------------------------------- #
# Build + write                                                           #
# ---------------------------------------------------------------------- #


def build_hardware_json(
    graph: MachineConfigGraph,
    machine_name: str,
) -> dict[str, Any]:
    """Build the hardware.json v2 payload from a parsed Klipper graph.

    Walks the graph, derives ids for every entity, emits the
    three-record endstop per switch, and lets the strict
    :class:`HardwareJson` model validate the cross-references.

    Raises :class:`pydantic.ValidationError` if any reference is
    unresolved. The exception handler in the router converts that
    into the structured 400 envelope for the toast channel.
    """

    axes_letters = AxisBuilder(graph).build()
    # The LinuxCNC ``Axis`` list is in canonical order (X, Y, Z, ...).
    # We re-derive the letter from the Axis object so the iteration
    # below matches the consumer's expectations.
    letters_in_order = [axis.letter.lower() for axis in axes_letters]

    # Stepper records — one per Klipper stepper section.
    # ``graph.steppers`` is keyed by axis letter (``x``, ``y``, ``z``);
    # the section name lives on the Stepper object as
    # ``section_name``. The id is derived from the section name so
    # naming stays consistent across the axes / steppers / drivers lists.
    stepper_records: list[dict[str, Any]] = []
    stepper_id_by_letter: dict[str, str] = {}
    for letter, stepper in graph.steppers.items():
        payload = _stepper_payload(stepper.section_name, stepper)
        stepper_records.append(payload)
        stepper_id_by_letter[letter.lower()] = payload["id"]

    # Driver records — one per stepper. When the parser learns
    # about other driver types we extend the lookup.
    driver_records: list[dict[str, Any]] = [
        _driver_payload(payload["driver"], stepper)
        for payload, stepper in zip(stepper_records, graph.steppers.values())
    ]

    # Axis records — one per unique axis letter. Multi-motor axes
    # share the letter; the underlying steppers are still listed
    # individually.
    axes_records: list[dict[str, Any]] = []
    for letter in letters_in_order:
        stepper_ids = [
            stepper_id_by_letter[name]
            for name, stepper in graph.steppers.items()
            if stepper.axis.lower() == letter
        ]
        endstop_ids = [
            _endstop_id(endstop_name, "endstop")
            for endstop_name, endstop in graph.endstop_switches.items()
            if endstop.stepper and endstop.stepper.axis.lower() == letter
        ]
        axes_records.append(_axis_payload(letter, stepper_ids, endstop_ids))

    # Endstop records — three per switch. The endstop_switch name
    # becomes the ``endstop_id`` (the Klipper switch identity).
    endstop_records: list[dict[str, Any]] = []
    for endstop_name, endstop in graph.endstop_switches.items():
        if not endstop.stepper:
            continue
        axis_letter = endstop.stepper.axis.lower()
        stepper_id = stepper_id_by_letter.get(
            axis_letter,
            f"stepper_{axis_letter}",
        )
        endstop_records.extend(
            _endstop_records(
                endstop_name,
                endstop.name,
                stepper_id,
                endstop.pin,
                endstop.position,
            )
        )

    # Heater records — one per heater-shaped section.
    heater_records: list[dict[str, Any]] = []
    temperature_sensor_records: list[dict[str, Any]] = []
    fan_records: list[dict[str, Any]] = []
    for heater_section, heater in graph.heaters.items():
        heater_records.append(_heater_payload(heater_section, heater))
        if heater.sensor_pin:
            temperature_sensor_records.append(
                _temperature_sensor_payload(heater_section, heater)
            )
        if heater.heater_pin:
            fan_records.append(_fan_payload(heater_section, heater))

    # HAL type from the MCU section if present.
    hal_type = "remora"
    if hasattr(graph, "mcu") and graph.mcu:
        hal_type = getattr(graph.mcu, "hal_type", "remora")

    # Validate the structured payload against the strict model.
    # The cross-reference validator runs here and surfaces any
    # unresolved id as a single ValueError with the full list.
    payload = {
        "version": "2.0",
        "machine": machine_name,
        "source": "KlipperToLinuxCNCCompiler",
        "kinematics": graph.printer.kinematics if graph.printer else "cartesian",
        "hal_type": hal_type,
        "axes": axes_records,
        "steppers": stepper_records,
        "drivers": driver_records,
        "endstops": endstop_records,
        "heaters": heater_records,
        "temperature_sensors": temperature_sensor_records,
        "fans": fan_records,
    }

    model = _HardwareJsonModel.model_validate(payload)
    serialised = _model_to_dict(model)

    logger.info(
        "hardware.json v2: %d axes, %d steppers, %d drivers, %d endstops, "
        "%d heaters, %d temperature_sensors, %d fans",
        len(axes_records),
        len(stepper_records),
        len(driver_records),
        len(endstop_records),
        len(heater_records),
        len(temperature_sensor_records),
        len(fan_records),
    )
    return serialised


def write_hardware_json(
    path: Path,
    graph: MachineConfigGraph,
    machine_name: str,
) -> None:
    """Write hardware.json to disk."""
    payload = build_hardware_json(graph, machine_name)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


__all__ = ["build_hardware_json", "write_hardware_json"]
