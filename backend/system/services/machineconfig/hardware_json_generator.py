"""Generate ``hardware.json`` — the backend's high-level hardware overview.

``hardware.json`` is the canonical record of every pin, stepper,
driver, tool, sensor, endstop, and fan the backend knows about.
It is derived from the parsed Klipper graph at compile time and
consumed by everything that needs to query the hardware
(deployment tools, the console, future Remora firmware flasher)
without parsing the raw config again.

Shape
-----
The payload is the ``hardware.json`` v2 model — see
:mod:`backend.models.machineconfig.hardware_json_models`.
The model is flat with explicit ``id`` fields and string
references; the cross-reference validator walks the graph in one
pass to enforce every reference resolves into the right list.

Axes carry a string ``id`` (the canonical LinuxCNC letter —
``x``, ``y``, ``z``, ``a``, ...) and a ``joint_numbers: list[int]``
listing every driving joint's integer ``joint_number``. Joints
(physical motors) keep their own string ``id`` and integer
``joint_number`` so the runtime can map a wire ``joint_number``
to a Remora stepgen channel ``remora.joint.{N}.*``.

IDs are auto-assigned from the Klipper section name. ``[stepper_x]``
becomes ``id: "stepper_x"``; ``[heater_bed]`` becomes
``id: "heater_bed"``. The same convention applies to switches —
``[endstop_switch X_MIN]`` (or an inline ``endstop_pin:`` on
``[stepper_x]``) becomes a single ``Endstop`` record with id
``"endstop_x_min"`` carrying only ``{id, pin}``. Each axis hosts
the switch via a single ``endstop: "endstop_x_min"`` reference; one
switch may be referenced by multiple axes.

The ``tools`` list is the operator-facing view: every ``[extruder]``,
``[heater_bed]``, ``[heater_generic]``, ``[spindle]``, and
``[spindle_analog]`` becomes one Tool entry with the appropriate
``type`` discriminator. SpindleDigital tools expose their HAL hooks
(signal aliases for the digital path, ``pwm_pin`` / ``enable_pin``
for the analog path); extruder / heated_bed tools expose their
heater fields plus references into the separate ``temperature_sensors``
and ``fans`` lists.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from models.machineconfig import MachineConfigGraph
from models.machineconfig.hardware_json_models import (
    HardwareJson as _HardwareJsonModel,
    to_dict as _model_to_dict,
)
from .axis_builder import AxisBuilder, stepgen_scale

logger = logging.getLogger("backend.services.machineconfig.hardware_json_generator")

#: Connection types that identify a Remora SPI/Ethernet board MCU.
#: Used only to set ``McuInfo.is_remora`` — a transparency flag on
#: the hardware.json MCU inventory, not a code path of its own (the
#: dedicated Remora ``config.txt`` flash-payload generator was
#: retired along with the deprecated compiler; see HANDOFF.md).
REMORA_CONNECTION_TYPES: frozenset[str] = frozenset({"remora-spi", "remora-eth"})


# ---------------------------------------------------------------------- #
# ID derivation                                                           #
# ---------------------------------------------------------------------- #


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


def _endstop_id(endstop_section: str) -> str:
    """Canonical id for an endstop record.

    One record per Klipper ``[endstop_switch NAME]`` section; the id
    is ``endstop_<NAME>``. Axes reference this id via
    ``Axis.endstop`` so the runtime can find the pin. The id is
    lower-cased to match the canonical ``^[a-z][a-z0-9_]*$``
    pattern enforced by the hardware.json v2 model.
    """
    return f"endstop_{endstop_section.lower()}"


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


def _endstop_record(endstop_section: str, pin: str) -> dict[str, Any]:
    """Build the top-level endstop record (one per Klipper switch).

    Mirrors the Klipper source shape: just ``{id, pin}``. The
    positional field (``Axis.pos``) and any behavioural tag are
    carried on the axis that hosts the switch; one record can be
    referenced by any number of axes.
    """
    return {
        "id": _endstop_id(endstop_section),
        "pin": pin,
    }


# ---------------------------------------------------------------------- #
# Tool payload                                                            #
# ---------------------------------------------------------------------- #


def _friendly_tool_name(tool_id: str, tool_type: str) -> str:
    """Return the operator-facing chip label for a tool entry.

    The frontend ToolPanel renders this string verbatim in the
    header chip row. The id remains the canonical machine handle;
    the name is purely cosmetic and can be edited later via a
    profile override without touching the graph.
    """
    # Strip the ``heater_`` prefix that the canonical id carries so
    # the operator sees ``bed`` rather than ``heater_bed`` on the
    # chip. SpindleDigital tools get a parenthetical so two spindles on
    # one machine are visually distinguishable.
    bare = tool_id
    if bare.startswith("heater_"):
        bare = bare[len("heater_"):]
    if tool_type == "spindle_analog":
        return f"{bare.replace('_', ' ').title()} (Analog)"
    if tool_type == "spindle_digital":
        return f"{bare.replace('_', ' ').title()} (Digital)"
    return bare.replace("_", " ").title()


def _tool_payload_from_heater(heater_section: str, h) -> dict[str, Any]:
    """Build a Tool entry from a Klipper heater-shaped section.

    ``[extruder]`` becomes ``type: "extruder"``; everything else
    (``[heater_bed]``, ``[heater_generic]``, ...) becomes
    ``type: "heated_bed"``. The id stays the canonical
    ``_heater_id`` form so existing references (PID alias mapping,
    HAL wiring) keep working unchanged.

    The ``sensor`` and ``fan`` fields are string references the
    cross-reference validator resolves into ``temperature_sensors``
    and ``fans`` respectively — neither record is embedded in the
    tool entry.
    """
    is_extruder = heater_section == "extruder" or heater_section.startswith("extruder")
    tool_type = "extruder" if is_extruder else "heated_bed"
    tool_id = _heater_id(heater_section)
    return {
        "id": tool_id,
        "name": _friendly_tool_name(tool_id, tool_type),
        "type": tool_type,
        "sensor": _temperature_sensor_id(heater_section),
        "heater_pin": h.heater_pin,
        "fan": _fan_id(heater_section) if h.heater_pin else None,
        "control": h.control,
        "min_temp": h.min_temp,
        "max_temp": h.max_temp,
    }


def _tool_payload_from_spindle_analog(spindle) -> dict[str, Any]:
    """Build a Tool entry for the ``[spindle_analog]`` section.

    Analog spindle — no RPM feedback path. The ToolPanel renders
    the analog card (Set Speed + Enable / Disable) and the HAL
    generator wires ``pwm_pin`` + ``enable_pin`` onto a Remora PWM
    module.
    """
    return {
        "id": "spindle_analog",
        "name": _friendly_tool_name("spindle_analog", "spindle_analog"),
        "type": "spindle_analog",
        "pwm_pin": spindle.pwm_pin,
        "enable_pin": spindle.enable_pin,
        "min_rpm": spindle.min_rpm,
        "max_rpm": spindle.max_rpm,
    }


def _tool_payload_from_spindle_digital(spindle_id: str, spindle) -> dict[str, Any]:
    """Build a Tool entry for one ``[spindle ...]`` section.

    Digital spindle — carries the HAL signal aliases the vfdmod
    driver expects. The ToolPanel renders the digital card
    (Actual RPM + Target RPM + Forward / Reverse / Stop) and the
    HAL generator emits the live net lines for populated signals,
    with ``# TODO: manual hookup`` placeholders for empty ones.

    ``spindle_id`` is the canonical id (``spindle_digital`` for the
    bare ``[spindle]`` form, ``spindle_digital_test`` for
    ``[spindle test]``, ...). Each instance gets its own tool
    record so the runtime can address them independently.

    The ``signal_*`` key names mirror the
    :class:`backend.tools_config_mapper.SpindleDigitalPins`
    fields (``target_rpm``, ``actual_out``, ``is_connected``,
    ``error_count``, ``last_error``, ``spindle_at_speed``). Fields
    with no source on the underlying ``[spindle]`` model
    (``actual_out``, ``error_count``) are emitted as ``None`` so the
    operator can wire them by hand.
    """
    return {
        "id": spindle_id,
        "name": _friendly_tool_name(spindle_id, "spindle_digital"),
        "type": "spindle_digital",
        "min_rpm": spindle.min_rpm,
        "max_rpm": spindle.max_rpm,
        "signal_spindle_at_speed": spindle.at_speed1_signal,
        "signal_target_rpm": spindle.target_frequency_signal,
        "signal_actual_out": None,
        "signal_is_connected": spindle.is_connected_signal,
        "signal_error_count": None,
        "signal_last_error": spindle.last_error_signal,
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


def _standalone_fan_payload(fan_section: str, fan) -> dict[str, Any]:
    """Build a fan entry from a dedicated ``[fan]`` Klipper section.

    The id is the canonical ``derive_fan_name(section_header)`` form
    (``fan``, ``fan_generic``, ``fan_generic_part_cooling``, ...). The
    runtime Python controllers address the fan by this id; the
    ``_fan_id`` helper (heater-derived) is reserved for fans that
    piggyback on a heater's ``heater_pin``.
    """
    payload: dict[str, Any] = {
        "id": fan.name or fan_section,
        "pin": fan.pin,
    }
    if fan.max_power is not None:
        # ``max_power`` (0.0–1.0) is the PWM duty-cycle ceiling. The
        # Remora board JSON uses an 8-bit ``pwm_max`` field; the
        # ``config_txt`` generator reads ``max_power`` and scales it.
        # Persisting it here lets the runtime reconstruct the same
        # mapping without re-reading ``config.txt``.
        payload["max_power"] = round(float(fan.max_power), 4)
    return payload


# ---------------------------------------------------------------------- #
# Stepper payload                                                         #
# ---------------------------------------------------------------------- #


def _stepper_payload(stepper_section: str, stepper) -> dict[str, Any]:
    """Build a joint entry's payload dict.

    Motion-envelope fields (``position_min``, ``position_max``,
    ``position_endstop``) live on the owning ``Axis`` — not here.
    The joint record carries only the per-motor identity and
    scaling: the driver id, the three pin fields, ``microsteps``,
    ``rotation_distance``, and the optional ``homing_speed``.

    ``joint_number`` is filled in by ``build_hardware_json`` after
    the joint_records list is assembled so the numbering can walk
    the canonical axis order; it starts as ``None`` here and is
    re-stamped before the payload is returned. The driver id is
    ``driver_<stepper_id>`` so a one-to-one relationship holds by
    default.
    """
    return {
        "id": _stepper_id(stepper_section),
        "joint_number": None,
        "driver": _driver_id(None, stepper_section),
        "step_pin": stepper.step_pin,
        "dir_pin": stepper.dir_pin,
        "enable_pin": stepper.enable_pin,
        "microsteps": stepper.microsteps,
        "rotation_distance": _fmt_float(stepper.rotation_distance),
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


def _axis_payload(
    letter: str,
    joint_numbers: list[int],
    endstop_id: str | None,
    position_max: float | None,
    position_endstop: float | None,
) -> dict[str, Any]:
    """Build an axis entry.

    The axis is identified by its canonical LinuxCNC ``letter`` —
    ``x``, ``y``, ``z``, ``a``, ... — emitted as the string ``id``
    field. ``joint_numbers`` lists every joint that drives the axis
    (one element for a single-motor axis; multiple for a multi-motor
    axis like a dual-motor Y).

    ``endstop_id`` is a single string id referencing a top-level
    ``Endstop`` record (or ``None`` when the axis has no endstop);
    one endstop record can be referenced by multiple axes.
    ``position_endstop`` carries ``stepper.position_endstop`` (or
    the ``[endstop_switch] position`` override) so the runtime can
    validate the homing sequence without re-reading the source
    profile. ``position_max`` carries the axis travel limit (from
    the primary stepper's ``position_max``). Fields with ``None``
    values are dropped during serialisation.
    """
    return {
        "id": letter.lower(),
        "joint_numbers": joint_numbers,
        "endstop": endstop_id,
        "position_max": position_max,
        "position_endstop": position_endstop,
    }


# ---------------------------------------------------------------------- #
# Build + write                                                           #
# ---------------------------------------------------------------------- #


def build_hardware_json(
    graph: MachineConfigGraph,
    machine_name: str,
) -> dict[str, Any]:
    """Build the hardware.json v2 payload from a parsed Klipper graph.

    Walks the graph, derives ids for every entity, emits one endstop
    record per switch (with the inferred ``type`` for the runtime),
    and lets the strict :class:`HardwareJson` model validate the
    cross-references.

    Raises :class:`pydantic.ValidationError` if any reference is
    unresolved. The exception handler in the router converts that
    into the structured 400 envelope for the toast channel.
    """

    axes_letters = AxisBuilder(graph).build()
    # The LinuxCNC ``Axis`` list is in canonical order (X, Y, Z, ...).
    # We re-derive the letter from the Axis object so the iteration
    # below matches the consumer's expectations.
    letters_in_order = [axis.letter.lower() for axis in axes_letters]

    # Joint records — one per Klipper stepper section. Emitted under
    # the ``joints`` top-level key on the wire (the legacy name was
    # ``steppers``; the field was renamed to match LinuxCNC's joint
    # vocabulary since the payload already mirrors the per-motor
    # ``[JOINT_N]`` granularity).
    # ``graph.steppers`` is keyed by section suffix (``x``, ``y``,
    # ``y1``, ...) — NOT by axis letter, since a dual-motor axis has
    # more than one entry sharing the same ``stepper.axis``. The id
    # is built from that dict key (not ``stepper.section_name``,
    # which reconstructs ``f"stepper_{stepper.axis}"`` and would
    # collide for every extra motor on one axis) so naming stays
    # unique across the joints / drivers lists.
    joint_records: list[dict[str, Any]] = []
    joint_id_by_letter: dict[str, str] = {}
    for letter, stepper in graph.steppers.items():
        payload = _stepper_payload(f"stepper_{letter}", stepper)
        joint_records.append(payload)
        joint_id_by_letter[letter.lower()] = payload["id"]

    # Driver records — one per joint. When the parser learns
    # about other driver types we extend the lookup.
    driver_records: list[dict[str, Any]] = [
        _driver_payload(payload["driver"], stepper)
        for payload, stepper in zip(joint_records, graph.steppers.values())
    ]

    # Axis records — one per unique axis letter. Multi-motor axes
    # share the letter; the underlying joints are still listed
    # individually. Each axis carries one ``endstop`` reference,
    # one ``position_max``, and one ``position_endstop``. The
    # ``position_max`` is lifted from the primary stepper of the
    # letter; the endstop reference and ``position_endstop`` are
    # populated by the two passes below; a separate
    # ``[endstop_switch NAME]`` section takes precedence over the
    # inline form (a Klipper config can override the inferred
    # ``<AXIS>_MIN`` name).
    axis_state: dict[str, dict[str, Any]] = {
        letter: {
            "endstop_id": None,
            "position_max": None,
            "position_endstop": None,
        }
        for letter in letters_in_order
    }
    endstop_records: list[dict[str, Any]] = []

    # 0. ``position_max`` / ``position_endstop`` lift — take both
    #    axis-coordinate values from the primary (first) stepper of
    #    each axis letter. For multi-motor axes all joints share the
    #    same axis-level motion envelope; the first is canonical.
    #    ``None`` on axes whose primary stepper omits the fields.
    #    ``position_endstop`` may be overridden later by an explicit
    #    ``[endstop_switch] position:`` override (path 2 below).
    for letter in letters_in_order:
        stepper = graph.steppers.get(letter)
        if stepper is not None:
            axis_state[letter]["position_max"] = stepper.position_max
            axis_state[letter]["position_endstop"] = (
                stepper.position_endstop
            )

    # 1. Inline endstops declared on ``[stepper_X]`` via
    #    ``endstop_pin: ...`` + optional ``position_endstop: ...``.
    #    The Klipper switch name defaults to ``<AXIS>_MIN`` (the
    #    LinuxCNC convention) when no explicit ``[endstop_switch]``
    #    section overrides it. Each switch becomes one top-level
    #    record; the owning axis gains an ``endstop`` reference and
    #    a ``position_endstop``.
    inline_endstop_names: set[str] = set()
    for letter, stepper in graph.steppers.items():
        if stepper.endstop_pin is None:
            continue
        endstop_section = f"{letter.upper()}_MIN"
        if endstop_section in inline_endstop_names:
            continue
        endstop_records.append(
            _endstop_record(endstop_section, stepper.endstop_pin)
        )
        inline_endstop_names.add(endstop_section)
        if letter.lower() in axis_state:
            axis_state[letter.lower()]["endstop_id"] = _endstop_id(
                endstop_section
            )
            axis_state[letter.lower()]["position_endstop"] = (
                stepper.position_endstop
            )

    # 2. Separate ``[endstop_switch NAME]`` sections. These take
    #    precedence over the inline form (a Klipper config can
    #    override the inferred ``<AXIS>_MIN`` name with an
    #    explicit one). Inline switches with the same name are
    #    skipped above. The owning axis is derived from
    #    ``EndstopSwitch.stepper.axis``.
    for endstop_name, endstop in graph.endstop_switches.items():
        if not endstop.stepper:
            continue
        axis_letter = endstop.stepper.axis.lower()
        if endstop.pin is not None:
            endstop_records.append(_endstop_record(endstop_name, endstop.pin))
        if axis_letter in axis_state:
            axis_state[axis_letter]["endstop_id"] = _endstop_id(endstop_name)
            # ``[endstop_switch] position`` wins when explicitly set;
            # otherwise fall back to the stepper's
            # ``position_endstop`` (which path 1 would have
            # inherited), and finally to whatever path 1 already
            # recorded (None for axes with no inline endstop).
            if endstop.position is not None:
                axis_state[axis_letter]["position_endstop"] = endstop.position
            elif axis_state[axis_letter]["position_endstop"] is None:
                axis_state[axis_letter]["position_endstop"] = (
                    endstop.stepper.position_endstop
                )

    # Stamp ``joint_number`` on every joint record in canonical
    # order: all X joints first, then Y, then Z, then A (extruders),
    # in declaration order within each letter. The number mirrors
    # the LinuxCNC-side ``Joint.joint_number`` so the runtime can map
    # a wire ``joint_number`` to ``remora.joint.{N}.scale`` etc.
    # deterministically regardless of the order the user wrote the
    # Klipper stepper sections in. This must run BEFORE the
    # axis-records assembly so each axis record can carry its
    # ``joint_numbers`` list.
    joint_number_by_letter: dict[str, int] = {}
    joint_number = 0
    for letter in letters_in_order:
        for letter_key, stepper in graph.steppers.items():
            if stepper.axis.lower() != letter:
                continue
            joint_id = joint_id_by_letter.get(letter_key)
            if joint_id is None:
                continue
            for record in joint_records:
                if record["id"] == joint_id:
                    record["joint_number"] = joint_number
                    joint_number_by_letter[letter_key] = joint_number
                    joint_number += 1
                    break

    # Now assemble the axis records with their endstop references
    # and lifted motion-envelope fields. Each axis record is keyed
    # by its canonical LinuxCNC letter (``id``) and lists every
    # driving joint by integer ``joint_numbers``.
    #
    # Note: only stepper-derived letters become axes here. The
    # extruder axis (``a``) is synthesised by ``AxisBuilder`` with
    # an empty joint list — we skip it and create the extruder
    # axis explicitly below from the synthesised extruder joint
    # records.
    axes_records: list[dict[str, Any]] = []
    for letter in letters_in_order:
        joint_numbers = [
            joint_number_by_letter[name]
            for name, stepper in graph.steppers.items()
            if stepper.axis.lower() == letter
            and name in joint_number_by_letter
        ]
        # Skip letters whose only axis came from the extruder
        # synthesis (AxisBuilder creates an empty ``a`` axis when
        # an extruder exists; we don't want that empty axis on the
        # wire because the extruder gets its own axis built from
        # the synthesised joint records below).
        if not joint_numbers:
            continue
        state = axis_state[letter]
        axes_records.append(
            _axis_payload(
                letter,
                joint_numbers,
                state["endstop_id"],
                state["position_max"],
                state["position_endstop"],
            )
        )

    # Tool records — one per Klipper heater-shaped section plus one
    # per spindle variant. The temperature_sensors[] and fans[]
    # top-level lists keep getting seeded from heater-shaped
    # sections so the chart and the runtime fan registry don't
    # regress.
    tool_records: list[dict[str, Any]] = []
    temperature_sensor_records: list[dict[str, Any]] = []
    fan_records: list[dict[str, Any]] = []
    for heater_section, heater in graph.heaters.items():
        tool_records.append(_tool_payload_from_heater(heater_section, heater))
        if heater.sensor_pin:
            temperature_sensor_records.append(
                _temperature_sensor_payload(heater_section, heater)
            )
        if heater.heater_pin:
            fan_records.append(_fan_payload(heater_section, heater))
    if graph.spindle_analog is not None:
        tool_records.append(_tool_payload_from_spindle_analog(graph.spindle_analog))
    for spindle_id, spindle in graph.spindle_digitals.items():
        tool_records.append(
            _tool_payload_from_spindle_digital(spindle_id, spindle)
        )

    # Synthesise one joint entry per extruder tool. The extruder
    # lives under ``heaters`` on the Klipper side rather than as a
    # ``[stepper_*]`` section, so it never appears in
    # ``graph.steppers``; we add a synthetic joint record here so
    # the wire ``joints[]`` is a complete enumeration (matches the
    # LinuxCNC-side ``Joint`` list produced by ``AxisBuilder``).
    # Each extruder joint carries the extruder's pins + scaling
    # fields, exactly like a regular stepper, but has no driver
    # (drivers[] is motor-driver only) and an id matching its
    # ``tools[]`` entry.
    from models.machineconfig import Extruder
    extruder_joint_records: list[dict[str, Any]] = []
    for tool in tool_records:
        if tool.get("type") != "extruder":
            continue
        # Find the matching Extruder object on the graph by tool id.
        extruder_obj = None
        for section, h in graph.heaters.items():
            if not isinstance(h, Extruder):
                continue
            if _heater_id(section) == tool["id"]:
                extruder_obj = h
                break
        if extruder_obj is None:
            # Shouldn't happen — an ``extruder``-typed tool always
            # has a matching ``Extruder`` instance on the graph —
            # but skipping is safer than crashing the compile.
            continue
        extruder_joint_records.append(
            {
                "id": tool["id"],
                "joint_number": joint_number,
                "driver": None,
                "step_pin": getattr(extruder_obj, "step_pin", None),
                "dir_pin": getattr(extruder_obj, "dir_pin", None),
                "enable_pin": getattr(extruder_obj, "enable_pin", None),
                "microsteps": getattr(extruder_obj, "microsteps", None),
                "rotation_distance": _fmt_float(
                    getattr(extruder_obj, "rotation_distance", None)
                ),
            }
        )
        joint_number += 1
    joint_records.extend(extruder_joint_records)

    # Now that all joint records (steppers + synthesised extruders)
    # exist, create the extruder axis (canonical letter ``a``) and
    # append it to ``axes_records``. The earlier stepper-only loop
    # skipped letters with no steppers — the synthesised extruder
    # axis was deliberately excluded there because it would have
    # an empty ``joint_numbers`` list. We build it here from the
    # freshly-stamped extruder joint numbers.
    if extruder_joint_records:
        extruder_joint_numbers = [r["joint_number"] for r in extruder_joint_records]
        axes_records.append(
            _axis_payload(
                "a",
                extruder_joint_numbers,
                None,
                None,
                None,
            )
        )

    # Standalone fan sections (``[fan]``, ``[fan_generic foo]``) become
    # their own ``fans`` records keyed by the canonical id. The id is
    # what the runtime Python controllers address symbolically, so
    # naming is the contract.
    for fan_section, fan in graph.fans.items():
        fan_records.append(_standalone_fan_payload(fan_section, fan))

    # HAL type from the MCU section if present. With multi-MCU the
    # decision collapses to "remora" if any remora transport is
    # declared, otherwise the first declared MCU's transport (which
    # the HAL generator maps to "parallel" via
    # :func:`connection_to_hal_type`). The legacy back-compat
    # property :attr:`MachineConfigGraph.mcu` returns the first
    # entry, which matches the historical single-MCU flow.
    hal_type = "remora"
    primary_mcu = graph.mcu if hasattr(graph, "mcu") else None
    if primary_mcu is not None:
        hal_type = getattr(primary_mcu, "hal_type", "remora")
    # Multi-MCU inventory — every declared section becomes an
    # :class:`McuInfo` record. The list is empty when the profile
    # declares no MCU at all (back-compat: a v2 consumer that never
    # added the field sees ``[]``).
    mcu_records: list[dict[str, Any]] = []
    for name, mcu in graph.mcus.items():
        mcu_records.append(
            {
                "id": name,
                "connection": mcu.connection,
                "interface": mcu.interface,
                "board": mcu.board,
                "is_remora": mcu.connection in REMORA_CONNECTION_TYPES,
            }
        )

    # Validate the structured payload against the strict model.
    # The cross-reference validator runs here and surfaces any
    # unresolved id as a single ValueError with the full list.
    payload = {
        "version": "2.1",
        "machine": machine_name,
        "source": "KlipperToLinuxCNCCompiler",
        "kinematics": graph.printer.kinematics if graph.printer else "cartesian",
        "hal_type": hal_type,
        "axes": axes_records,
        "joints": joint_records,
        "drivers": driver_records,
        "endstops": endstop_records,
        "tools": tool_records,
        "temperature_sensors": temperature_sensor_records,
        "fans": fan_records,
        "mcus": mcu_records,
    }

    model = _HardwareJsonModel.model_validate(payload)
    serialised = _model_to_dict(model)

    logger.info(
        "hardware.json v2: %d axes, %d joints, %d drivers, %d endstops, "
        "%d tools, %d temperature_sensors, %d fans",
        len(axes_records),
        len(joint_records),
        len(driver_records),
        len(endstop_records),
        len(tool_records),
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
