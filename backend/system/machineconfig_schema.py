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
        # A CAN expansion board (BTT EBB42 ...) behind a remora-spi hub
        # (Remora-m8p CAN_PROTOCOL.md): digital I/O only so far.
        "remora-can",
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
    HEATER_FAN = "heater_fan"
    DUPLICATE_PIN_OVERRIDE = "duplicate_pin_override"
    ESTOP = "estop"
    PROBE = "probe"
    TOOL_LENGTH_SENSOR = "tool_length_sensor"
    BED_MESH = "bed_mesh"
    HOMING_OVERRIDE = "homing_override"
    Z_TILT = "z_tilt"
    NEOPIXEL = "neopixel"
    OUTPUT_PIN = "output_pin"
    INPUT_PIN = "input_pin"
    TEMPERATURE_SENSOR = "temperature_sensor"


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
        # Klipper's second, slower approach and the retract between —
        # used by a Z homed on the probe (probe:z_virtual_endstop).
        "second_homing_speed",
        "homing_retract_dist",
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
# The probe component — a single digital input, ``motion.probe-input``
# (`.agent/component/probe.md`). Genuinely optional, unlike ``[estop]``:
# a machine with no touch probe simply never declares this section at
# all (no "empty block is still valid" requirement — there's nothing
# UI-driven to fall back to).
# x_offset / y_offset / z_offset: Klipper's meaning — the probe sits
# x_offset, y_offset from the nozzle; the nozzle is z_offset above the
# bed when the probe triggers (`.agent/component/probe.md`).
PROBE_KEYS = frozenset({"pin", "x_offset", "y_offset", "z_offset"})
# The tool-length sensor (tool setter) — a second digital input that
# is OR-ed with the probe into ``motion.probe-input``
# (`.agent/component/probe.md` § 3). Same single optional ``pin``.
TOOL_LENGTH_SENSOR_KEYS = frozenset({"pin"})
# Bed mesh / Z compensation (`.agent/component/bed_mesh.md`). Minimal
# for now: the probe grid only; the mesh itself is probed / edited at
# runtime and applied by the Remora `compensation` HAL component.
# Klipper's probing keys (``mesh_min`` / ``mesh_max``, travel), plus this
# compiler's own ``probe_speed`` (Klipper keeps it in ``[probe]``).
BED_MESH_KEYS = frozenset({
    "probe_count", "mesh_min", "mesh_max", "speed", "horizontal_move_z",
    "probe_speed", "zero_reference_position",
})
# A homing routine (Klipper's ``[homing_override]``,
# `.agent/component/homing_override.md`): ``gcode`` lines run in order,
# ``G28 <axes>`` among them homes; ``axes`` are the axes whose home
# button runs it (default all).
HOMING_OVERRIDE_KEYS = frozenset({"gcode", "axes"})
# Klipper's ``[z_tilt]`` (`.agent/component/z_tilt.md`): one pivot per Z
# motor, the probe points, travel; ``probe_speed`` / ``max_adjust`` are
# this compiler's own (Klipper keeps the probe speed in ``[probe]``).
# Klipper's ``[neopixel NAME]`` (`.agent/component/neopixel.md`): a WS2812 /
# SK6812 chain; ``segments`` (this compiler's own) groups LEDs that share
# one colour channel — a Remora board has only 6 set points.
NEOPIXEL_KEYS = frozenset({
    "pin", "chain_count", "color_order", "initial_RED", "initial_GREEN",
    "initial_BLUE", "initial_WHITE", "segments",
})
Z_TILT_KEYS = frozenset({
    "z_positions", "points", "speed", "horizontal_move_z", "retries",
    "retry_tolerance", "probe_speed", "max_adjust",
})
# Generic I/O (`.agent/component/io_pins.md`), Klipper syntax. An
# output is switched from the UI (or PWM with ``pwm: True``); an input
# is shown in the UI and can run G-code on its edges.
OUTPUT_PIN_KEYS = frozenset({"pin", "pwm", "value", "shutdown_value", "cycle_time", "scale"})
# A standalone temperature reading (`.agent/component/temperature_sensor.md`):
# a thermistor on a board pin, any float HAL pin or signal
# (``sensor_type: hal``), the host's CPU (``temperature_host``, with an
# optional ``thermal_zone``) or the Remora board's MCU (``temperature_mcu``).
TEMPERATURE_SENSOR_KEYS = frozenset({"sensor_type", "sensor_pin", "thermal_zone"})
INPUT_PIN_KEYS = frozenset({
    "pin", "rising_ngc", "falling_ngc", "rising_halpin_set", "falling_halpin_set",
})
# Fan sections accept ``pin``, an optional ``max_power`` (0.0–1.0,
# the runtime's ``PWM Max`` in the Remora board JSON), and an optional
# ``shutdown_speed`` (duty on estop/shutdown — Klipper's own field,
# ingested as data today; not yet wired into a HAL safety circuit,
# see `.agent/component/fan.md`).
#
# Every other keyword Klipper's real `[fan]`/`[heater_fan]` docs
# define is recognised but ignored — this compiler assumes a plain
# two-pin fan (no tachometer wire at all, so no RPM sense) driven at
# a fixed PWM cycle by whichever MCU router binds the pin, so none of
# these have anywhere to go: ``cycle_time`` / ``hardware_pwm`` (fixed
# PWM cycle), ``off_below`` (no minimum-duty modelling yet),
# ``enable_pin`` (no separate power-enable line modelled),
# ``tachometer_pin``/``tachometer_ppr``/``tachometer_poll_interval``
# (no tachometer on a two-pin fan), ``kick_start_time`` (no startup-kick
# stage).
FAN_IGNORED_KEYS = frozenset(
    {
        "cycle_time",
        "hardware_pwm",
        "off_below",
        "enable_pin",
        "tachometer_pin",
        "tachometer_ppr",
        "tachometer_poll_interval",
        "kick_start_time",
    }
)
FAN_KEYS = frozenset({"pin", "max_power", "shutdown_speed"}) | FAN_IGNORED_KEYS
# ``[heater_fan <name>]`` shares every ``[fan]`` keyword (Klipper's own
# docs: "See the fan section for a description of the above
# parameters") plus its own association fields: which heater drives
# it, the temperature that turns it on, and the speed it runs at once
# triggered. Unlike a plain fan, a heater_fan is never operator/G-code
# commandable — the HAL wires it straight off the heater's own sensor
# reading (`.agent/component/fan.md` § 3's "kind: heater" chain).
HEATER_FAN_KEYS = (
    frozenset({"pin", "max_power", "shutdown_speed", "heater", "heater_temp", "fan_speed"})
    | FAN_IGNORED_KEYS
)

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
# ``board_reset_pin`` is constrained to ``remora-spi``/``remora-eth``
# only — a pin on the Remora board itself, emitted as the firmware's
# `"Reset Pin"` module (the reference `machine_config/example/ender3/
# config.txt` always carries one); no other connection type reads it.
# The host side of a ``remora-spi`` link — parameters of the
# ``loadrt remora-spi`` driver line (and of the ``remora-upload --sync``
# line before it), not firmware pins, spelled exactly like the driver's
# own parameters (keys are case-sensitive, as ``pid_Kp``), so the block
# reads one-to-one like the loadrt line: ``SPI_freq`` (Hz) **or**
# ``SPI_clk_div`` (bcm2835 divider, Pi 3/4 — mutually exclusive, the
# divider depends on the Pi's core clock), ``PRU_base_freq`` (Hz),
# ``spi_cs_pin`` / ``spi_cs_chip``
# (chip select on a GPIO — the BTT CB1 has none on the header),
# ``reset_pin`` / ``reset_chip`` (a host GPIO that resets the board)
# and ``sync_config`` (default on: put ``config_<mcu>.txt`` on the
# board's SD card at every LinuxCNC start). ``interface`` is the
# spidev path. Only valid on ``remora-spi``.
REMORA_SPI_HOST_KEYS = frozenset(
    {
        "SPI_freq",
        "SPI_clk_div",
        "PRU_base_freq",
        "spi_cs_pin",
        "spi_cs_chip",
        "reset_pin",
        "reset_chip",
        "sync_config",
    }
)

# The CAN side of a Remora hub (firmware ``"CAN"`` block in the hub's
# config.txt — Remora-m8p CAN_PROTOCOL.md): ``can_bitrate`` (default
# 1000000) and ``can_status_bit`` (the LinuxCNC input bit that is 1 only
# while every mandatory node runs — wired into the E-stop chain;
# default 15 when the hub has a mandatory node). Only on ``remora-spi``.
REMORA_CAN_HUB_KEYS = frozenset({"can_bitrate", "can_status_bit"})

# A CAN node (``connection: remora-can``): ``canbus_uuid`` (required,
# the node's 12-hex-digit UUID, Klipper's own key name), ``can_node``
# (1-15, default: next free in declaration order), ``can_hub`` (the
# hub's MCU name, default: the machine's only remora-spi MCU),
# ``mandatory`` (default true: losing it means E-stop). Only on
# ``remora-can``. No lost / safe state key: every pin falls back to Low
# (outputs' Safe State, inputs' Lost State) — the machine must be safe at Low.
REMORA_CAN_NODE_KEYS = frozenset({"canbus_uuid", "can_node", "can_hub", "mandatory"})

MCU_KEYS = frozenset(
    {
        "connection",
        "interface",
        "board",
        "baud_rate",
        "node_id",
        "parity",
        "board_reset_pin",
    }
) | REMORA_SPI_HOST_KEYS | REMORA_CAN_HUB_KEYS | REMORA_CAN_NODE_KEYS

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
    SectionKind.HEATER_FAN: HEATER_FAN_KEYS,
    SectionKind.DUPLICATE_PIN_OVERRIDE: DUPLICATE_PIN_OVERRIDE_KEYS,
    SectionKind.ESTOP: ESTOP_KEYS,
    SectionKind.PROBE: PROBE_KEYS,
    SectionKind.TOOL_LENGTH_SENSOR: TOOL_LENGTH_SENSOR_KEYS,
    SectionKind.BED_MESH: BED_MESH_KEYS,
    SectionKind.HOMING_OVERRIDE: HOMING_OVERRIDE_KEYS,
    SectionKind.Z_TILT: Z_TILT_KEYS,
    SectionKind.NEOPIXEL: NEOPIXEL_KEYS,
    SectionKind.OUTPUT_PIN: OUTPUT_PIN_KEYS,
    SectionKind.INPUT_PIN: INPUT_PIN_KEYS,
    SectionKind.TEMPERATURE_SENSOR: TEMPERATURE_SENSOR_KEYS,
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
# heater_fan mirrors Klipper's own syntax — always named in practice
# ("[heater_fan heatbreak_cooling_fan]"), bare accepted too for
# consistency with every other component here:
#   [heater_fan]                    -> bare, id = "heater_fan"
#   [heater_fan heatbreak_cooling]  -> named, id = "heater_fan_heatbreak_cooling"
_HEATER_FAN_SECTION = re.compile(
    r"^heater_fan(?:\s+(?P<name>[A-Za-z0-9_.-]+))?$"
)
# Digital spindle sections mirror the fan naming pattern:
#   [spindle]            -> bare (canonical id = "spindle_digital")
#   [spindle test]       -> named instance, id = "spindle_digital_test"
# The canonical id is intentionally distinct from the section header
# so the runtime vocabulary ("spindle_digital" type tag) and the
# Klipper vocabulary ("spindle" section header) stay decoupled.
# [output_pin case_light] / [input_pin my_button] — always named; the
# name is the component id (webgui.<name>).
_OUTPUT_PIN_SECTION = re.compile(r"^output_pin\s+(?P<name>[A-Za-z0-9_]+)$")
_INPUT_PIN_SECTION = re.compile(r"^input_pin\s+(?P<name>[A-Za-z0-9_]+)$")
# [temperature_sensor chamber] — always named; the name is the sensor id
# (webgui.<name>), so it takes the hardware.json id pattern directly.
# [neopixel sb_leds] — always named; the name is the LED id.
_NEOPIXEL_SECTION = re.compile(r"^neopixel\s+(?P<name>[a-z][a-z0-9_]*)$")
_TEMPERATURE_SENSOR_SECTION = re.compile(r"^temperature_sensor\s+(?P<name>[a-z][a-z0-9_]*)$")
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

    if section == "machine":
        # `[machine]`, not `[printer]` — Klipper's own vocabulary
        # (inherited since this compiler reuses Klipper's `.cfg`
        # syntax) makes no sense for a CNC profile that was never a
        # 3D printer. Only this name is accepted; `[printer]` now
        # falls through to `UnsupportedSectionError` like any other
        # unrecognised section. `_parse_printer`'s own
        # `kinematics != "cartesian"` check still rejects anything
        # but a Cartesian machine — the only kinematics this compiler
        # (or LinuxCNC `trivkins`, which every generated INI assumes)
        # supports.
        return SectionSchema(SectionKind.PRINTER, PRINTER_KEYS, "machine")

    if section == "duplicate_pin_override":
        return SectionSchema(
            SectionKind.DUPLICATE_PIN_OVERRIDE,
            DUPLICATE_PIN_OVERRIDE_KEYS,
            "duplicate_pin_override",
        )

    if section == "estop":
        return SectionSchema(SectionKind.ESTOP, ESTOP_KEYS, "estop")

    if section == "probe":
        return SectionSchema(SectionKind.PROBE, PROBE_KEYS, "probe")

    if section == "bed_mesh":
        return SectionSchema(SectionKind.BED_MESH, BED_MESH_KEYS, "bed_mesh")

    if section == "homing_override":
        return SectionSchema(SectionKind.HOMING_OVERRIDE, HOMING_OVERRIDE_KEYS, "homing_override")

    if section == "z_tilt":
        return SectionSchema(SectionKind.Z_TILT, Z_TILT_KEYS, "z_tilt")

    output_match = _OUTPUT_PIN_SECTION.fullmatch(section)
    if output_match:
        return SectionSchema(SectionKind.OUTPUT_PIN, OUTPUT_PIN_KEYS, output_match.group("name"))

    input_match = _INPUT_PIN_SECTION.fullmatch(section)
    if input_match:
        return SectionSchema(SectionKind.INPUT_PIN, INPUT_PIN_KEYS, input_match.group("name"))

    neopixel_match = _NEOPIXEL_SECTION.fullmatch(section)
    if neopixel_match:
        return SectionSchema(SectionKind.NEOPIXEL, NEOPIXEL_KEYS, neopixel_match.group("name"))

    sensor_match = _TEMPERATURE_SENSOR_SECTION.fullmatch(section)
    if sensor_match:
        return SectionSchema(
            SectionKind.TEMPERATURE_SENSOR, TEMPERATURE_SENSOR_KEYS, sensor_match.group("name")
        )

    if section == "tool_length_sensor":
        return SectionSchema(
            SectionKind.TOOL_LENGTH_SENSOR, TOOL_LENGTH_SENSOR_KEYS, "tool_length_sensor"
        )

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

    heater_fan_match = _HEATER_FAN_SECTION.fullmatch(section)
    if heater_fan_match:
        return SectionSchema(
            SectionKind.HEATER_FAN,
            HEATER_FAN_KEYS,
            section,
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
    "BED_MESH_KEYS",
    "HOMING_OVERRIDE_KEYS",
    "Z_TILT_KEYS",
    "NEOPIXEL_KEYS",
    "INPUT_PIN_KEYS",
    "OUTPUT_PIN_KEYS",
    "DUPLICATE_PIN_OVERRIDE_KEYS",
    "ENDSTOP_SWITCH_KEYS",
    "ESTOP_KEYS",
    "EXTRUDER_KEYS",
    "FAN_KEYS",
    "FAN_IGNORED_KEYS",
    "HEATER_FAN_KEYS",
    "HEATER_KEYS",
    "MCU_KEYS",
    "PRINTER_IGNORED_KEYS",
    "PRINTER_KEYS",
    "PROBE_KEYS",
    "TEMPERATURE_SENSOR_KEYS",
    "TOOL_LENGTH_SENSOR_KEYS",
    "SECTION_SCHEMAS",
    "SPINDLE_ANALOG_KEYS",
    "SPINDLE_KEYS",
    "STEPPER_KEYS",
    "SectionKind",
    "SectionSchema",
    "schema_for_section",
]
