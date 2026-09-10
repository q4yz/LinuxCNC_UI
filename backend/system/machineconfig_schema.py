"""Strict section schemas for Klipper-style machine configurations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


#: Allowed values for the ``connection`` keyword of an ``[mcu]`` section.
#:
#: ``rs485`` / ``remora-spi`` / ``remora-eth`` / ``parallelport`` /
#: ``dummy``. Anything else raises :class:`InvalidConnectionError`.
#: ``connection`` is the single source of truth for MCU behaviour —
#: the capability class and the HAL router both branch on it, with no
#: derived boolean (``is_remora`` was removed for exactly this
#: reason), so adding a value here is the one change a new transport
#: needs at ingestion time.
#: ``vfd_rs485`` is the canonical name for a VFD/spindle controller on
#: a serial bus — a controller is an MCU like any other, which is what
#: lets ``[spindle]`` declare pins instead of naming a protocol (see
#: ``.agent/component/mcu_vfd_rs485.md``). ``rs485`` is kept as an
#: alias so profiles written before the rename keep parsing.
#:
#: ``ethercat`` and ``usb_arduino`` are documented transports
#: (``.agent/component/mcu_ethercat.md`` / ``mcu_usb_arduino.md``) that
#: parse and validate today; their HAL routers are not implemented yet,
#: so compiling a machine that routes pins onto them raises
#: ``UnsupportedMcuError`` — the same honest gap ``remora-eth`` has.
ALLOWED_CONNECTION_TYPES: frozenset[str] = frozenset(
    {
        "vfd_rs485",
        "rs485",
        "remora-spi",
        "remora-eth",
        "parallelport",
        "ethercat",
        "usb_arduino",
        "dummy",
    }
)


class SectionKind(str, Enum):
    """Supported machine-configuration section types."""

    MCU = "mcu"
    PRINTER = "printer"
    STEPPER = "stepper"
    ENDSTOP_SWITCH = "endstop_switch"
    EXTRUDER = "extruder"
    HEATER = "heater"
    SPINDLE = "spindle"
    SPINDLE_ANALOG = "spindle_analog"
    TMC2209 = "tmc2209"
    FAN = "fan"
    DUPLICATE_PIN_OVERRIDE = "duplicate_pin_override"
    ESTOP = "estop"


@dataclass(frozen=True, slots=True)
class SectionSchema:
    """Schema selected for one concrete configuration section.

    ``allowed_keys`` is the strict set of keywords the section may
    declare. Unknown keywords raise :class:`UndefinedKeywordError`.
    """

    kind: SectionKind
    allowed_keys: frozenset[str]
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
# A global, opt-in exception to the pin-conflict guard — not a
# component, never emits HAL. See
# `.agent/component/README.md` § 3: two independently-named signals
# can legitimately share one physical *input* pin (the operator has
# verified the real wiring), but the compiler can't tell that from a
# collision an operator typo would also produce. Listing the pin here
# is the explicit "yes, this one's on purpose."
DUPLICATE_PIN_OVERRIDE_KEYS = frozenset({"pins"})
STEPPER_KEYS = frozenset(
    {
        "step_pin",
        "dir_pin",
        "enable_pin",
        "rotation_distance",
        "microsteps",
        "full_steps_per_rotation",
        "endstop_pin",
        "position_endstop",
        "position_min",
        "position_max",
        "homing_speed",
        # Class-B (Remora) per-joint position-loop tuning — real,
        # optional `setp remora.joint.N.*` knobs the reference config
        # actually uses (`machine_config/example/ender3/ender3.hal`:
        # `deadband` on joint 2, `pgain` on joint 3). No effect on
        # class A, which has no such loop to tune.
        "deadband",
        "pgain",
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
SPINDLE_KEYS = frozenset(
    {
        "max_rpm",
        "min_rpm",
        "spindle_number",
        "rpm_scale",
        "run_pin",
        "reverse_pin",
        "speed_pin",
        "speed_fb_pin",
        "at_speed_pin",
        "fault_pin",
        "is_connected_pin",
        "error_count_pin",
    }
)
SPINDLE_ANALOG_KEYS = frozenset({"pwm_pin", "enable_pin", "max_rpm", "min_rpm"})
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
# The E-stop component. Both fields are pins, not protocols, like
# every other component (`.agent/component/README.md` § 1) — and both
# are optional: an empty ``[estop]`` block is valid (UI-only trigger,
# see `.agent/component/estop.md`), physical wiring is opt-in on top.
ESTOP_KEYS = frozenset({"fault_pin", "out_pin"})
# Fan sections accept a single ``pin`` plus an optional ``max_power``
# (0.0–1.0) which the runtime uses as the ``PWM Max`` value in the
# Remora board JSON. ``cycle_time`` / ``hardware_pwm`` / ``off_below``
# are recognised by Klipper but ignored by the compiler (the Remora
# firmware uses a fixed PWM cycle).
FAN_KEYS = frozenset({"pin", "max_power", "cycle_time", "hardware_pwm", "off_below"})
FAN_IGNORED_KEYS = frozenset({"cycle_time", "hardware_pwm", "off_below"})

# MCU sections accept the transport / board / serial keywords.
# ``connection`` is the single source of truth for how the HAL
# compiler routes this MCU (capability class, router choice) — no
# derived boolean like ``is_remora``; consumers branch on the
# connection value itself. ``interface`` is a free-form transport
# selector (``/dev/serial/by-id/...`` for RS-485, ``socket://...``
# for Remora-Eth, etc.). ``board`` is the operator-visible board
# name, optional and **never autofilled** — HAL generation cares
# about protocols and device paths, not PCB names. The RS-485 trio
# (``baud_rate`` / ``node_id`` / ``parity``) is constrained by the
# parser to ``vfd_rs485`` (and legacy ``rs485``) sections only.
MCU_KEYS = frozenset(
    {"connection", "interface", "board", "baud_rate", "node_id", "parity"}
)

SECTION_SCHEMAS: dict[SectionKind, frozenset[str]] = {
    SectionKind.MCU: MCU_KEYS,
    SectionKind.PRINTER: PRINTER_KEYS,
    SectionKind.STEPPER: STEPPER_KEYS,
    SectionKind.ENDSTOP_SWITCH: ENDSTOP_SWITCH_KEYS,
    SectionKind.EXTRUDER: EXTRUDER_KEYS,
    SectionKind.HEATER: HEATER_KEYS,
    SectionKind.SPINDLE: SPINDLE_KEYS,
    SectionKind.SPINDLE_ANALOG: SPINDLE_ANALOG_KEYS,
    SectionKind.TMC2209: TMC2209_KEYS,
    SectionKind.FAN: FAN_KEYS,
    SectionKind.DUPLICATE_PIN_OVERRIDE: DUPLICATE_PIN_OVERRIDE_KEYS,
    SectionKind.ESTOP: ESTOP_KEYS,
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
# Digital spindle sections mirror the fan naming pattern:
#   [spindle]            -> bare (canonical id = "spindle_digital")
#   [spindle test]       -> named instance, id = "spindle_digital_test"
# The canonical id is intentionally distinct from the section header
# so the runtime vocabulary ("spindle_digital" type tag) and the
# Klipper vocabulary ("spindle" section header) stay decoupled.
_SPINDLE_DIGITAL_SECTION = re.compile(
    r"^spindle(?:\s+(?P<name>[A-Za-z0-9_.-]+))?$"
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

    if section == "duplicate_pin_override":
        return SectionSchema(
            SectionKind.DUPLICATE_PIN_OVERRIDE,
            DUPLICATE_PIN_OVERRIDE_KEYS,
            "duplicate_pin_override",
        )

    if section == "estop":
        return SectionSchema(SectionKind.ESTOP, ESTOP_KEYS, "estop")

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

    spindle_match = _SPINDLE_DIGITAL_SECTION.fullmatch(section.lower())
    if spindle_match:
        # The schema object_name is the raw section header so the
        # parser can derive the canonical id via
        # :func:`parser.derive_spindle_name`. Empty ``name`` -> "spindle"
        # (bare form) -> canonical id "spindle_digital".
        return SectionSchema(
            SectionKind.SPINDLE,
            SPINDLE_KEYS,
            section,
        )

    if section.lower() == "spindle_analog":
        return SectionSchema(
            SectionKind.SPINDLE_ANALOG, SPINDLE_ANALOG_KEYS, "spindle_analog"
        )

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
    "ALLOWED_CONNECTION_TYPES",
    "ALLOWED_KEYS",
    "DUPLICATE_PIN_OVERRIDE_KEYS",
    "ENDSTOP_SWITCH_KEYS",
    "ESTOP_KEYS",
    "EXTRUDER_KEYS",
    "FAN_KEYS",
    "FAN_IGNORED_KEYS",
    "HEATER_KEYS",
    "MCU_KEYS",
    "PRINTER_IGNORED_KEYS",
    "PRINTER_KEYS",
    "SECTION_SCHEMAS",
    "SPINDLE_ANALOG_KEYS",
    "SPINDLE_KEYS",
    "STEPPER_KEYS",
    "SectionKind",
    "SectionSchema",
    "schema_for_section",
]
