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
    HEATER = "heater"
    SPINDLE = "spindle"
    TMC2209 = "tmc2209"
    FAN = "fan"


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
        "max_z_velocity",
        "max_z_accel",
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
        "position_min",
        "position_max",
        "homing_speed",
    }
)
ENDSTOP_SWITCH_KEYS = frozenset({"stepper", "pin", "position", "type"})

# Heater-shaped sections share the same key set. The extruder section
# extends this with stepper + filament drive fields.
HEATER_KEYS = frozenset(
    {
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
EXTRUDER_KEYS = frozenset(
    HEATER_KEYS
    | {
        "step_pin",
        "dir_pin",
        "enable_pin",
        "microsteps",
        "rotation_distance",
        "nozzle_diameter",
        "filament_diameter",
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
# Fan sections accept a single ``pin`` plus an optional ``max_power``
# (0.0–1.0) which the runtime uses as the ``PWM Max`` value in the
# Remora board JSON. ``cycle_time`` / ``hardware_pwm`` / ``off_below``
# are recognised by Klipper but ignored by the compiler (the Remora
# firmware uses a fixed PWM cycle).
FAN_KEYS = frozenset({"pin", "max_power", "cycle_time", "hardware_pwm", "off_below"})
FAN_IGNORED_KEYS = frozenset({"cycle_time", "hardware_pwm", "off_below"})

SECTION_SCHEMAS: dict[SectionKind, frozenset[str] | None] = {
    SectionKind.MCU: None,
    SectionKind.PRINTER: PRINTER_KEYS,
    SectionKind.STEPPER: STEPPER_KEYS,
    SectionKind.ENDSTOP_SWITCH: ENDSTOP_SWITCH_KEYS,
    SectionKind.EXTRUDER: EXTRUDER_KEYS,
    SectionKind.HEATER: HEATER_KEYS,
    SectionKind.SPINDLE: SPINDLE_KEYS,
    SectionKind.TMC2209: TMC2209_KEYS,
    SectionKind.FAN: FAN_KEYS,
}

# Public alias for callers that only need the allowed-key lookup.
ALLOWED_KEYS = SECTION_SCHEMAS

_MCU_SECTION = re.compile(r"^mcu(?:\s+(?P<name>[A-Za-z0-9_.-]+))?$")
_STEPPER_SECTION = re.compile(r"^stepper_(?P<name>[A-Za-z0-9_]+)$")
_ENDSTOP_SECTION = re.compile(
    r"^endstop_switch\s+(?P<name>[A-Za-z0-9_.-]+)$"
)
_TMC2209_SECTION = re.compile(r"^tmc2209\s+(?P<name>[A-Za-z0-9_.-]+)$")
# Extruder accepts three forms:
#   [extruder]               -> bare (only one allowed)
#   [extruder1], [extruder2] -> numbered (Klipper compatibility syntax)
#   [extruder hotend]        -> named instance
# The numbered form is normalised to the named form in derive_heater_name
# so the runtime never needs to know which syntax the user typed.
_EXTRUDER_SECTION = re.compile(
    r"^extruder(?:(?P<num>\d+)|\s+(?P<name>[A-Za-z0-9_.-]+))?$"
)
# Heater generic accepts:
#   [heater_bed]             -> exact match (covered below)
#   [heater_generic]         -> bare
#   [heater_generic chamber] -> named instance
_HEATER_GENERIC_SECTION = re.compile(
    r"^heater_generic(?:\s+(?P<name>[A-Za-z0-9_.-]+))?$"
)
# Fan sections mirror the extruder / heater_generic naming pattern:
#   [fan]                    -> bare (canonical id = "fan")
#   [fan_generic]            -> bare heater-style id
#   [fan_generic part_cooling] -> named instance, id = "fan_generic_part_cooling"
_FAN_SECTION = re.compile(
    r"^fan(?:_generic)?(?:\s+(?P<name>[A-Za-z0-9_.-]+))?$"
)


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

    extruder_match = _EXTRUDER_SECTION.fullmatch(section)
    if extruder_match:
        # The schema object_name is the bare section header, not the
        # normalised heater name. The parser assigns the heater name
        # via derive_heater_name; the schema needs the raw match so
        # consumers can introspect the numbered/named form.
        return SectionSchema(
            SectionKind.EXTRUDER,
            EXTRUDER_KEYS,
            section,
        )

    if section == "heater_bed":
        return SectionSchema(SectionKind.HEATER, HEATER_KEYS, "heater_bed")

    heater_generic_match = _HEATER_GENERIC_SECTION.fullmatch(section)
    if heater_generic_match:
        return SectionSchema(
            SectionKind.HEATER,
            HEATER_KEYS,
            section,
        )

    if section == "spindle":
        return SectionSchema(SectionKind.SPINDLE, SPINDLE_KEYS, "spindle")

    fan_match = _FAN_SECTION.fullmatch(section)
    if fan_match:
        # The schema object_name is the bare section header so the
        # parser can derive the canonical id (mirrors the extruder /
        # heater_generic naming convention). Empty ``name`` -> "fan".
        return SectionSchema(
            SectionKind.FAN,
            FAN_KEYS,
            section,
        )

    return None


__all__ = [
    "ALLOWED_KEYS",
    "ENDSTOP_SWITCH_KEYS",
    "EXTRUDER_KEYS",
    "FAN_KEYS",
    "FAN_IGNORED_KEYS",
    "HEATER_KEYS",
    "PRINTER_IGNORED_KEYS",
    "PRINTER_KEYS",
    "SECTION_SCHEMAS",
    "SPINDLE_KEYS",
    "STEPPER_KEYS",
    "SectionKind",
    "SectionSchema",
    "schema_for_section",
]
