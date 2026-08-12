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
:mod:`backend.modules.machineconfig.models.hardware_json_models`.
The model is flat with explicit ``id`` fields and string
references; the cross-reference validator walks the graph in one
pass to enforce every reference resolves into the right list.

IDs are auto-assigned from the Klipper section name. ``[stepper_x]``
becomes ``id: "stepper_x"``; ``[heater_bed]`` becomes
``id: "heater_bed"``. The same convention applies to switches —
``[endstop_switch X_MIN]`` produces three records (one per role)
with the same ``endstop_id`` (``"X_MIN"``) and distinct record ids.

The ``tools`` list is the operator-facing view: every ``[extruder]``,
``[heater_bed]``, ``[heater_generic]``, ``[spindle]``, and
``[spindle_analog]`` becomes one Tool entry with the appropriate
``type`` discriminator. Spindle tools expose their HAL hooks
(signal aliases for the digital path, ``pwm_pin`` / ``enable_pin``
for the analog path); extruder / heated_bed tools expose their
heater fields plus references into the separate ``temperature_sensors``
and ``fans`` lists.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from ..models import MachineConfigGraph
from ..models.hardware_json_models import (
    HardwareJson as _HardwareJsonModel,
    to_dict as _model_to_dict,
)
from .config_txt_generator import REMORA_CONNECTION_TYPES
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


def _endstop_id(endstop_section: str) -> str:
    """Canonical id for an endstop record.

    One record per Klipper ``[endstop_switch NAME]`` section; the id
    is ``endstop_<NAME>``. Inline ``Axis.endstops[*].id`` entries
    reference this same id so the runtime can find the full record.
    The id is lower-cased to match the canonical ``^[a-z][a-z0-9_]*$``
    pattern enforced by the hardware.json v2 model.
    """
    return f"endstop_{endstop_section.lower()}"


def _infer_endstop_type(stepper) -> Optional[str]:
    """Return the endstop behaviour inferred from the Klipper stepper.

    Rules:

    * ``"Home"`` when ``position_endstop`` is explicitly set on the
      stepper — the switch is the home reference.
    * ``"Estop"`` when only ``endstop_pin`` is set — the switch is
      a safety stop, not used for homing.
    * ``None`` when neither is present — the endstop is macros-only
      and has no kinematic role (rare; future use).

    The inference keeps the Klipper source as the single source of
    truth without requiring a new ``switch_type:`` keyword.
    """
    if stepper.position_endstop is not None:
        return "Home"
    if stepper.endstop_pin is not None:
        return "Estop"
    return None


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


def _endstop_record(
    endstop_section: str,
    stepper_id: str,
    pin: str,
    pos: float | None,
    endstop_type: Optional[str],
) -> dict[str, Any]:
    """Build the top-level endstop record (one per Klipper switch).

    Carries the full HAL-wiring fields (``pin``, ``stepper``) plus
    the inferred ``type`` so the runtime can route the switch to
    the right HAL signal. ``pos`` is the position on the axis
    (defaults to ``0.0`` when the Klipper source omits
    ``position_endstop``).
    """
    pos_value = pos if pos is not None else 0.0
    return {
        "id": _endstop_id(endstop_section),
        "type": endstop_type,
        "pos": pos_value,
        "stepper": stepper_id,
        "pin": pin,
    }


def _endstop_inline_view(endstop_section: str, pos: float | None, endstop_type: Optional[str]) -> dict[str, Any]:
    """Build the inline ``Axis.endstops[*]`` entry.

    Carries only ``{id, type, pos}`` — enough for the runtime to
    find the matching top-level record and route the switch.
    """
    pos_value = pos if pos is not None else 0.0
    return {
        "id": _endstop_id(endstop_section),
        "type": endstop_type,
        "pos": pos_value,
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
    # chip. Spindle tools get a parenthetical so two spindles on
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


def _tool_payload_from_spindle_digital(spindle) -> dict[str, Any]:
    """Build a Tool entry for the ``[spindle]`` section.

    Digital spindle — carries the HAL signal aliases the vfdmod
    driver expects. The ToolPanel renders the digital card
    (Actual RPM + Target RPM + Forward / Reverse / Stop) and the
    HAL generator emits the live net lines for populated signals,
    with ``# TODO: manual hookup`` placeholders for empty ones.
    """
    return {
        "id": "spindle_digital",
        "name": _friendly_tool_name("spindle_digital", "spindle_digital"),
        "type": "spindle_digital",
        "min_rpm": spindle.min_rpm,
        "max_rpm": spindle.max_rpm,
        "signal_at_speed": spindle.at_speed1_signal,
        "signal_forward": None,
        "signal_reverse": None,
        "signal_on": spindle.is_connected_signal,
        "signal_pwm": spindle.target_frequency_signal,
        "signal_istop": None,
        "signal_estop": spindle.last_error_signal,
        "signal_vfd_enable": None,
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


def _axis_payload(
    letter: str,
    stepper_ids: list[str],
    endstop_views: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build an axis entry.

    The axis id is the lower-case letter of the canonical stepper it
    owns. Multi-motor axes share the id so the axes list stays
    unique; the underlying steppers are still listed individually.
    ``endstop_views`` is a list of inline ``{id, type, pos}`` dicts;
    the full endstop records (with ``pin`` / ``stepper``) live at
    the top-level ``endstops`` array.
    """
    return {
        "id": _axis_id(None, letter),
        "steppers": stepper_ids,
        "endstops": endstop_views,
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
    # individually. Inline ``endstops`` views are built below when
    # the endstop records are emitted (so we can dedupe by axis
    # letter in one pass).
    inline_views_by_letter: dict[str, list[dict[str, Any]]] = {
        letter: [] for letter in letters_in_order
    }
    endstop_records: list[dict[str, Any]] = []

    # 1. Inline endstops declared on ``[stepper_X]`` via
    #    ``endstop_pin: ...`` + optional ``position_endstop: ...``.
    #    The Klipper switch name defaults to ``<AXIS>_MIN`` (the
    #    LinuxCNC convention) when no explicit ``[endstop_switch]``
    #    section overrides it.
    seen_endstop_names: set[str] = set()
    for letter, stepper in graph.steppers.items():
        if stepper.endstop_pin is None:
            continue
        endstop_section = f"{letter.upper()}_MIN"
        if endstop_section in seen_endstop_names:
            # A separate ``[endstop_switch]`` already covered this
            # switch; skip the inline duplicate so the hardware.json
            # stays a 1-record-per-switch list.
            continue
        stepper_id = stepper_id_by_letter.get(
            letter.lower(),
            f"stepper_{letter.lower()}",
        )
        endstop_type = _infer_endstop_type(stepper)
        endstop_records.append(
            _endstop_record(
                endstop_section,
                stepper_id,
                stepper.endstop_pin,
                stepper.position_endstop,
                endstop_type,
            )
        )
        seen_endstop_names.add(endstop_section)
        if letter.lower() in inline_views_by_letter:
            inline_views_by_letter[letter.lower()].append(
                _endstop_inline_view(
                    endstop_section,
                    stepper.position_endstop,
                    endstop_type,
                )
            )

    # 2. Separate ``[endstop_switch NAME]`` sections. These take
    #    precedence over the inline form (a Klipper config can
    #    override the inferred ``<AXIS>_MIN`` name with an explicit
    #    one). Inline switches with the same name are skipped above.
    for endstop_name, endstop in graph.endstop_switches.items():
        if not endstop.stepper:
            continue
        axis_letter = endstop.stepper.axis.lower()
        stepper_id = stepper_id_by_letter.get(
            axis_letter,
            f"stepper_{axis_letter}",
        )
        endstop_type = _infer_endstop_type(endstop.stepper)
        endstop_records.append(
            _endstop_record(
                endstop_name,
                stepper_id,
                endstop.pin,
                endstop.position,
                endstop_type,
            )
        )
        seen_endstop_names.add(endstop_name)
        if axis_letter in inline_views_by_letter:
            inline_views_by_letter[axis_letter].append(
                _endstop_inline_view(
                    endstop_name, endstop.position, endstop_type
                )
            )

    # Now assemble the axis records with their inline views.
    axes_records: list[dict[str, Any]] = []
    for letter in letters_in_order:
        stepper_ids = [
            stepper_id_by_letter[name]
            for name, stepper in graph.steppers.items()
            if stepper.axis.lower() == letter
        ]
        axes_records.append(
            _axis_payload(letter, stepper_ids, inline_views_by_letter[letter])
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
    if graph.spindle_digital is not None:
        tool_records.append(_tool_payload_from_spindle_digital(graph.spindle_digital))

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
        "version": "2.0",
        "machine": machine_name,
        "source": "KlipperToLinuxCNCCompiler",
        "kinematics": graph.printer.kinematics if graph.printer else "cartesian",
        "hal_type": hal_type,
        "axes": axes_records,
        "steppers": stepper_records,
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
        "hardware.json v2: %d axes, %d steppers, %d drivers, %d endstops, "
        "%d tools, %d temperature_sensors, %d fans",
        len(axes_records),
        len(stepper_records),
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
