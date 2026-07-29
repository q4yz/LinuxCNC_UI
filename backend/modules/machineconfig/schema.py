"""Strict section schemas for Klipper-style machine configurations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class SectionKind(str, Enum):
    """Supported machine-configuration section types."""

    MCU = "mcu"
    PRINTER = "printer"
    STEPPER = "stepper"
    ENDSTOP_SWITCH = "endstop_switch"
    EXTRUDER = "extruder"
    HEATER_BED = "heater_bed"
    SPINDLE = "spindle"
    TMC2209 = "tmc2209"


@dataclass(frozen=True, slots=True)
class SectionSchema:
    """Schema selected for one concrete configuration section.

    ``allowed_keys`` is ``None`` only for MCU sections. MCU configuration is
    intentionally bypassed because LinuxCNC does not consume Klipper's MCU
    transport settings.
    """

    kind: SectionKind
    allowed_keys: frozenset[str] | None
    object_name: str | None = None


PRINTER_KEYS = frozenset(
    {
        "kinematics",
        "max_velocity",
        "max_accel",
        "minimum_cruise_ratio",
        "square_corner_velocity",
    }
)
PRINTER_IGNORED_KEYS = frozenset(
    {"minimum_cruise_ratio", "square_corner_velocity"}
)
STEPPER_KEYS = frozenset(
    {
        "step_pin",
        "dir_pin",
        "enable_pin",
        "rotation_distance",
        "microsteps",
        "endstop_pin",
        "position_endstop",
        "position_max",
    }
)
ENDSTOP_SWITCH_KEYS = frozenset({"stepper", "pin", "position", "type"})
EXTRUDER_KEYS = frozenset(
    {
        "step_pin",
        "dir_pin",
        "enable_pin",
        "microsteps",
        "rotation_distance",
        "nozzle_diameter",
        "filament_diameter",
        "heater_pin",
        "sensor_type",
        "sensor_pin",
        "control",
        "pid_Kp",
        "pid_Ki",
        "pid_Kd",
        "min_temp",
        "max_temp",
    }
)
HEATER_BED_KEYS = frozenset(
    {
        "heater_pin",
        "sensor_type",
        "sensor_pin",
        "control",
        "min_temp",
        "max_temp",
    }
)
SPINDLE_KEYS = frozenset({"pwm_pin", "enable_pin", "max_rpm"})
TMC2209_KEYS = frozenset(
    {
        "uart_pin",
        "run_current",
        "stealthchop_threshold",
        "microsteps",
        "interpolate",
        "hold_current",
        "sense_resistor",
    }
)

SECTION_SCHEMAS: dict[SectionKind, frozenset[str] | None] = {
    SectionKind.MCU: None,
    SectionKind.PRINTER: PRINTER_KEYS,
    SectionKind.STEPPER: STEPPER_KEYS,
    SectionKind.ENDSTOP_SWITCH: ENDSTOP_SWITCH_KEYS,
    SectionKind.EXTRUDER: EXTRUDER_KEYS,
    SectionKind.HEATER_BED: HEATER_BED_KEYS,
    SectionKind.SPINDLE: SPINDLE_KEYS,
    SectionKind.TMC2209: TMC2209_KEYS,
}

# Public alias for callers that only need the allowed-key lookup.
ALLOWED_KEYS = SECTION_SCHEMAS

_MCU_SECTION = re.compile(r"^mcu(?:\s+(?P<name>[A-Za-z0-9_.-]+))?$")
_STEPPER_SECTION = re.compile(r"^stepper_(?P<name>[A-Za-z0-9_]+)$")
_ENDSTOP_SECTION = re.compile(
    r"^endstop_switch\s+(?P<name>[A-Za-z0-9_.-]+)$"
)
_TMC2209_SECTION = re.compile(r"^tmc2209\s+(?P<name>[A-Za-z0-9_.-]+)$")


def schema_for_section(section: str) -> SectionSchema | None:
    """Return the schema matching ``section``, or ``None`` if unsupported."""

    mcu_match = _MCU_SECTION.fullmatch(section)
    if mcu_match:
        return SectionSchema(
            SectionKind.MCU,
            SECTION_SCHEMAS[SectionKind.MCU],
            mcu_match.group("name") or "mcu",
        )

    if section == "printer":
        return SectionSchema(SectionKind.PRINTER, PRINTER_KEYS, "printer")

    stepper_match = _STEPPER_SECTION.fullmatch(section)
    if stepper_match:
        return SectionSchema(
            SectionKind.STEPPER,
            STEPPER_KEYS,
            stepper_match.group("name"),
        )

    endstop_match = _ENDSTOP_SECTION.fullmatch(section)
    if endstop_match:
        return SectionSchema(
            SectionKind.ENDSTOP_SWITCH,
            ENDSTOP_SWITCH_KEYS,
            endstop_match.group("name"),
        )

    tmc2209_match = _TMC2209_SECTION.fullmatch(section)
    if tmc2209_match:
        return SectionSchema(
            SectionKind.TMC2209,
            TMC2209_KEYS,
            tmc2209_match.group("name"),
        )

    exact_sections = {
        "extruder": SectionKind.EXTRUDER,
        "heater_bed": SectionKind.HEATER_BED,
        "spindle": SectionKind.SPINDLE,
    }
    kind = exact_sections.get(section)
    if kind is None:
        return None
    return SectionSchema(kind, SECTION_SCHEMAS[kind], section)


__all__ = [
    "ALLOWED_KEYS",
    "ENDSTOP_SWITCH_KEYS",
    "EXTRUDER_KEYS",
    "HEATER_BED_KEYS",
    "PRINTER_IGNORED_KEYS",
    "PRINTER_KEYS",
    "SECTION_SCHEMAS",
    "SPINDLE_KEYS",
    "STEPPER_KEYS",
    "SectionKind",
    "SectionSchema",
    "schema_for_section",
]
