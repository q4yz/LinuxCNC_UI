"""Tests for the strict Klipper configuration parser."""

from __future__ import annotations

import configparser

import pytest

from modules.machineconfig.models import EndstopSwitch, Extruder, Heater, Stepper
from modules.machineconfig.parser import (
    ConfigValidationError,
    DuplicateFanError,
    DuplicateHeaterError,
    DuplicateMcuSectionError,
    DuplicateStepperPinError,
    InvalidConnectionError,
    MachineConfigParser,
    MissingRequiredKeywordError,
    MultipleExtrudersError,
    UndefinedKeywordError,
    UndefinedMcuError,
    UnknownStepperError,
    derive_fan_name,
    derive_heater_name,
    split_pin,
)
from modules.machineconfig.schema import (
    ALLOWED_CONNECTION_TYPES,
    MCU_KEYS,
    SectionKind,
    schema_for_section,
)


def test_invalid_keyword_reports_section_and_key() -> None:
    """The parser demonstrates the zero-tolerance keyword contract."""

    config = """
[stepper_x]
step_pin: X_STEP
unexpected_pin: X_BAD
"""

    with pytest.raises(UndefinedKeywordError) as exc_info:
        MachineConfigParser().parse_string(config)

    assert exc_info.value.section == "stepper_x"
    assert exc_info.value.key == "unexpected_pin"
    assert "unexpected_pin" in str(exc_info.value)


def test_builds_linked_object_graph_and_ignores_mcu() -> None:
    config = """
[mcu controller]
connection: rs485
interface: /dev/ttyACM0

[printer]
kinematics: cartesian
max_velocity: 250
max_accel: 1200
minimum_cruise_ratio: 0.5

[endstop_switch y_max]
stepper: y
pin: ^PA1
position: 200
type: limit

[stepper_y]
step_pin: PB1
dir_pin: PB2
enable_pin: !PB3
rotation_distance: 40
microsteps: 16
position_max: 200

[extruder]
step_pin: PA4
heater_pin: PD5
sensor_pin: PA7
sensor_type: EPCOS 100K B57560G104F
control: pid
pid_Kp: 22.2
pid_Ki: 1.1
pid_Kd: 108.0
min_temp: 0
max_temp: 250

[heater_bed]
heater_pin: PD4
sensor_pin: PA6
sensor_type: EPCOS 100K B57560G104F
control: pid
pid_Kp: 54.0
pid_Ki: 0.7
pid_Kd: 948.0
min_temp: 0
max_temp: 130

[spindle_analog]
pwm_pin: PA6
max_rpm: 24000
"""

    machine = MachineConfigParser().parse_string(config)

    stepper = machine.steppers["y"]
    switch = machine.endstop_switches["y_max"]
    assert isinstance(stepper, Stepper)
    assert isinstance(switch, EndstopSwitch)
    assert switch.stepper is stepper
    assert stepper.endstops == [switch]
    assert machine.printer is not None
    assert machine.printer.max_velocity == 250.0
    # Heaters live in a single dict keyed by canonical name.
    assert "extruder" in machine.heaters
    assert "heater_bed" in machine.heaters
    assert isinstance(machine.heaters["extruder"], Extruder)
    assert isinstance(machine.heaters["heater_bed"], Heater)
    assert machine.heaters["extruder"].pid_Kp == 22.2
    assert machine.spindle_analog is not None
    assert machine.spindle_analog.pwm_pin == "PA6"
    assert machine.spindle_analog.max_rpm == 24000.0
    assert machine.spindle_digital is None
    # Multi-MCU: the named section ``[mcu controller]`` lives on
    # ``graph.mcus`` (new contract). Legacy callers can still reach
    # it via the ``primary_mcu`` / ``mcu`` back-compat property.
    assert "controller" in machine.mcus
    assert machine.mcu is machine.mcus["controller"]
    assert machine.mcu.connection == "rs485"
    assert machine.mcu.interface == "/dev/ttyACM0"


# ---------------------------------------------------------------------- #
# Spindle sections (analog + digital)                                     #
# ---------------------------------------------------------------------- #


def test_spindle_digital_section_parses_all_signal_aliases() -> None:
    """A `[spindle]` block with the full set of signal aliases
    round-trips into :class:`SpindleDigital` with each field
    populated and ``spindle_analog`` left None."""
    config = """
[spindle]
max_rpm: 24000
min_rpm: 5000
target_rpm_signal: TargetRpm
target_frequency_signal: TargetFrequency
rpm_out_signal: rpm-out
at_speed1_signal: at-speed1
at_speed2_signal: at-speed2
is_connected_signal: is-connected
error_count_signal: error-count
last_error_signal: last-error
"""
    machine = MachineConfigParser().parse_string(config)
    assert machine.spindle_digital is not None
    assert machine.spindle_digital.max_rpm == 24000.0
    assert machine.spindle_digital.min_rpm == 5000.0
    assert machine.spindle_digital.target_rpm_signal == "TargetRpm"
    assert machine.spindle_digital.target_frequency_signal == "TargetFrequency"
    assert machine.spindle_digital.rpm_out_signal == "rpm-out"
    assert machine.spindle_digital.at_speed1_signal == "at-speed1"
    assert machine.spindle_digital.at_speed2_signal == "at-speed2"
    assert machine.spindle_digital.is_connected_signal == "is-connected"
    assert machine.spindle_digital.error_count_signal == "error-count"
    assert machine.spindle_digital.last_error_signal == "last-error"
    assert machine.spindle_analog is None


def test_spindle_digital_section_with_no_keys_is_valid() -> None:
    """An empty `[spindle]` block produces a default
    :class:`SpindleDigital` (every field None). All signal fields
    are optional — the digital section is hooks-only."""
    config = """
[spindle]
"""
    machine = MachineConfigParser().parse_string(config)
    assert machine.spindle_digital is not None
    assert machine.spindle_digital.target_rpm_signal is None
    assert machine.spindle_digital.max_rpm is None
    assert machine.spindle_analog is None


def test_spindle_digital_rejects_physical_pin_keys() -> None:
    """`[spindle]` is the digital hooks section — physical pins
    belong in `[spindle_analog]` and must be rejected here."""
    config = """
[spindle]
pwm_pin: PA6
"""
    with pytest.raises(UndefinedKeywordError) as exc_info:
        MachineConfigParser().parse_string(config)
    assert exc_info.value.key == "pwm_pin"


def test_spindle_analog_rejects_signal_alias_keys() -> None:
    """`[spindle_analog]` is the PWM section — signal aliases
    belong in `[spindle]` and must be rejected here."""
    config = """
[spindle_analog]
target_rpm_signal: TargetRpm
"""
    with pytest.raises(UndefinedKeywordError) as exc_info:
        MachineConfigParser().parse_string(config)
    assert exc_info.value.key == "target_rpm_signal"


@pytest.mark.parametrize(
    "header",
    ["[spindle]", "[SPINDLE]", "[Spindle]"],
)
def test_spindle_section_header_is_case_insensitive(header: str) -> None:
    """Section header matching mirrors the vfdmod / Klipper
    "group names are case insensitive" convention."""
    config = f"""
{header}
max_rpm: 100
"""
    machine = MachineConfigParser().parse_string(config)
    assert machine.spindle_digital is not None
    assert machine.spindle_digital.max_rpm == 100.0


@pytest.mark.parametrize(
    "header",
    ["[spindle_analog]", "[SPINDLE_ANALOG]", "[Spindle_Analog]"],
)
def test_spindle_analog_header_is_case_insensitive(header: str) -> None:
    config = f"""
{header}
pwm_pin: PA6
"""
    machine = MachineConfigParser().parse_string(config)
    assert machine.spindle_analog is not None
    assert machine.spindle_analog.pwm_pin == "PA6"


def test_both_spindle_sections_can_coexist() -> None:
    """A profile may declare both the analog and digital spindle
    sections. The parser keeps them on separate graph fields."""
    config = """
[spindle_analog]
pwm_pin: PA6
enable_pin: PA7
max_rpm: 24000
min_rpm: 5000

[spindle]
max_rpm: 24000
min_rpm: 5000
target_rpm_signal: TargetRpm
"""
    machine = MachineConfigParser().parse_string(config)
    assert machine.spindle_analog is not None
    assert machine.spindle_analog.pwm_pin == "PA6"
    assert machine.spindle_digital is not None
    assert machine.spindle_digital.target_rpm_signal == "TargetRpm"


def test_endstop_unknown_target_is_rejected() -> None:
    config = """
[endstop_switch y_max]
stepper: y
pin: PA1
"""

    with pytest.raises(UnknownStepperError, match="unknown stepper 'y'"):
        MachineConfigParser().parse_string(config)


# ---------------------------------------------------------------------- #
# Heater extraction (issue: dynamic heater hardware.json)                 #
# ---------------------------------------------------------------------- #


def _full_block(name: str) -> str:
    """A complete, valid heater-shaped block with all required keys."""
    return f"""
[{name}]
heater_pin: PD5
sensor_pin: PA7
sensor_type: EPCOS 100K B57560G104F
control: pid
pid_Kp: 1.0
pid_Ki: 1.0
pid_Kd: 1.0
min_temp: 0
max_temp: 250
"""


class TestMultiExtruderSupport:
    """The parser recognises bare, numbered, and named extruder sections."""

    def test_extruder1_is_normalised_to_extruder_1(self) -> None:
        """[extruder1] is Klipper compatibility syntax → extruder_1."""
        config = _full_block("extruder") + _full_block("extruder1")
        graph = MachineConfigParser().parse_string(config)
        assert "extruder" in graph.heaters
        assert "extruder_1" in graph.heaters

    def test_extruder_with_name_uses_underscore(self) -> None:
        """[extruder hotend] produces the canonical name `extruder_hotend`."""
        config = _full_block("extruder") + _full_block("extruder hotend")
        graph = MachineConfigParser().parse_string(config)
        assert "extruder" in graph.heaters
        assert "extruder_hotend" in graph.heaters

    def test_two_bare_extruders_rejected(self) -> None:
        """Multiple bare [extruder] sections are rejected by ConfigParser.

        The strict configparser catches the duplicate section at
        parse time, before our custom validation runs. The
        ``MultipleExtrudersError`` class is preserved as a documented
        contract for the parser's intent, but is unreachable from a
        well-formed Klipper config.
        """
        import configparser

        config = _full_block("extruder") + _full_block("extruder")
        with pytest.raises(configparser.DuplicateSectionError):
            MachineConfigParser().parse_string(config)

    def test_duplicate_heater_name_rejected(self) -> None:
        """[extruder 1] and [extruder1] both compile to extruder_1 → error."""
        config = _full_block("extruder 1") + _full_block("extruder1")
        with pytest.raises(DuplicateHeaterError) as exc_info:
            MachineConfigParser().parse_string(config)
        assert exc_info.value.name == "extruder_1"


class TestHeaterGenericSupport:
    """heater_generic and named heater_generic sections are parsed."""

    def test_heater_generic_bare(self) -> None:
        config = _full_block("heater_generic")
        graph = MachineConfigParser().parse_string(config)
        assert "heater_generic" in graph.heaters

    def test_heater_generic_named(self) -> None:
        config = _full_block("heater_generic chamber")
        graph = MachineConfigParser().parse_string(config)
        assert "heater_generic_chamber" in graph.heaters


class TestHeaterFieldValidation:
    """Heater-shaped sections must carry the required physical-interface fields."""

    def test_missing_heater_pin_rejected(self) -> None:
        config = """
[extruder]
sensor_pin: PA7
control: pid
pid_Kp: 1.0
pid_Ki: 1.0
pid_Kd: 1.0
"""
        with pytest.raises(Exception) as exc_info:
            MachineConfigParser().parse_string(config)
        assert "heater_pin" in str(exc_info.value)

    def test_missing_sensor_pin_rejected(self) -> None:
        config = """
[extruder]
heater_pin: PD5
control: pid
pid_Kp: 1.0
pid_Ki: 1.0
pid_Kd: 1.0
"""
        with pytest.raises(Exception) as exc_info:
            MachineConfigParser().parse_string(config)
        assert "sensor_pin" in str(exc_info.value)

    def test_missing_control_rejected(self) -> None:
        config = """
[extruder]
heater_pin: PD5
sensor_pin: PA7
pid_Kp: 1.0
pid_Ki: 1.0
pid_Kd: 1.0
"""
        with pytest.raises(Exception) as exc_info:
            MachineConfigParser().parse_string(config)
        assert "control" in str(exc_info.value)

    def test_missing_pid_keys_when_control_pid_rejected(self) -> None:
        """When control=pid, the three pid_* keys are mandatory."""
        config = """
[extruder]
heater_pin: PD5
sensor_pin: PA7
control: pid
"""
        with pytest.raises(Exception) as exc_info:
            MachineConfigParser().parse_string(config)
        # The error should mention the missing pid_* keys.
        assert "pid_Kp" in str(exc_info.value) or "pid" in str(exc_info.value).lower()


class TestNamingHelperExport:
    """``derive_heater_name`` is exposed for callers outside the parser."""

    def test_is_callable_from_module_namespace(self) -> None:
        assert derive_heater_name("extruder1") == "extruder_1"
        assert derive_heater_name("heater_bed") == "heater_bed"


# ---------------------------------------------------------------------- #
# Duplicate-stepper-pin rule (issue #99)                                 #
# ---------------------------------------------------------------------- #


def test_duplicate_stepper_pin_step_pin_is_rejected() -> None:
    """Two steppers sharing ``step_pin`` raise DuplicateStepperPinError."""

    config = """
[stepper_x]
step_pin: PA0
dir_pin: PA1
enable_pin: !PA2

[stepper_y]
step_pin: PA0
dir_pin: PA3
enable_pin: !PA4
"""

    with pytest.raises(DuplicateStepperPinError) as exc_info:
        MachineConfigParser().parse_string(config)

    exc = exc_info.value
    assert exc.pin == "PA0"
    assert exc.pin_key == "step_pin"
    assert exc.section == "y"
    assert exc.axes == ["x", "y"]
    assert exc.kind == "duplicate_stepper_pin"
    # ``to_dict`` is the contract surface for the HTTP layer.
    payload = exc.to_dict()
    assert payload["section"] == "y"
    assert payload["key"] == "step_pin"
    assert payload["line"] is None
    assert payload["kind"] == "duplicate_stepper_pin"
    assert "PA0" in payload["message"]


def test_duplicate_stepper_pin_dir_pin_is_rejected() -> None:
    """Two steppers sharing ``dir_pin`` raise DuplicateStepperPinError."""

    config = """
[stepper_x]
step_pin: PA0
dir_pin: PA1
enable_pin: !PA2

[stepper_y]
step_pin: PA3
dir_pin: PA1
enable_pin: !PA4
"""

    with pytest.raises(DuplicateStepperPinError) as exc_info:
        MachineConfigParser().parse_string(config)

    exc = exc_info.value
    assert exc.pin == "PA1"
    assert exc.pin_key == "dir_pin"
    assert exc.axes == ["x", "y"]


def test_duplicate_stepper_pin_enable_pin_is_rejected() -> None:
    """Two steppers sharing ``enable_pin`` raise DuplicateStepperPinError."""

    config = """
[stepper_x]
step_pin: PA0
dir_pin: PA1
enable_pin: !PA2

[stepper_y]
step_pin: PA3
dir_pin: PA4
enable_pin: !PA2
"""

    with pytest.raises(DuplicateStepperPinError) as exc_info:
        MachineConfigParser().parse_string(config)

    exc = exc_info.value
    assert exc.pin == "!PA2"
    assert exc.pin_key == "enable_pin"
    assert exc.axes == ["x", "y"]


def test_duplicate_stepper_pin_endstop_pin_is_rejected() -> None:
    """Two steppers sharing ``endstop_pin`` raise DuplicateStepperPinError."""

    config = """
[stepper_x]
step_pin: PA0
dir_pin: PA1
enable_pin: !PA2
endstop_pin: ^PA3

[stepper_y]
step_pin: PA4
dir_pin: PA5
enable_pin: !PA6
endstop_pin: ^PA3
"""

    with pytest.raises(DuplicateStepperPinError) as exc_info:
        MachineConfigParser().parse_string(config)

    exc = exc_info.value
    assert exc.pin == "^PA3"
    assert exc.pin_key == "endstop_pin"
    assert exc.axes == ["x", "y"]


def test_duplicate_stepper_pin_is_a_config_validation_error() -> None:
    """DuplicateStepperPinError inherits from ConfigValidationError.

    The HTTP exception handler in ``router.py`` registers against the
    base class so every subclass — including the new
    ``DuplicateStepperPinError`` — flows through the same structured
    response shape. The isinstance guard below keeps that contract
    honest when the class hierarchy grows.
    """

    assert issubclass(DuplicateStepperPinError, ConfigValidationError)


def test_distinct_stepper_pins_for_multi_motor_y_are_accepted() -> None:
    """Multi-motor Y uses distinct pins and must parse cleanly.

    Regression guard: a naïve check that flagged every same-axis
    collision would reject the legitimate dual-motor case.
    """

    config = """
[stepper_x]
step_pin: PA0
dir_pin: PA1
enable_pin: !PA2

[stepper_y]
step_pin: PA3
dir_pin: PA4
enable_pin: !PA5

[stepper_y1]
step_pin: PA6
dir_pin: PA7
enable_pin: !PA8

[stepper_z]
step_pin: PA9
dir_pin: PA10
enable_pin: !PA11
"""

    graph = MachineConfigParser().parse_string(config)
    assert sorted(graph.steppers.keys()) == ["x", "y", "y1", "z"]


# ---------------------------------------------------------------------- #
# Fan section parsing (Phase 1)                                          #
# ---------------------------------------------------------------------- #


def test_fan_schema_recognises_bare_and_named_sections() -> None:
    """``[fan]``, ``[fan_generic]`` and ``[fan_generic foo]`` all
    map to the FAN SectionKind.
    """
    for header in ("fan", "fan_generic", "fan_generic part_cooling"):
        schema = schema_for_section(header)
        assert schema is not None, f"{header!r} returned None"
        assert schema.kind is SectionKind.FAN
    # A heater-style header must NOT match.
    assert schema_for_section("heater_bed").kind is not SectionKind.FAN


def test_fan_derive_name_matches_heater_pattern() -> None:
    """The canonical id follows the same shape as heaters."""
    assert derive_fan_name("fan") == "fan"
    assert derive_fan_name("fan_generic") == "fan_generic"
    assert derive_fan_name("fan_generic part_cooling") == "fan_generic_part_cooling"
    assert derive_fan_name("fan part_cooling") == "fan_part_cooling"


def test_fan_section_parses_into_graph() -> None:
    """A bare ``[fan]`` section becomes a :class:`Fan` on the graph."""
    config = """
[fan]
pin: PA8
"""
    graph = MachineConfigParser().parse_string(config)
    assert "fan" in graph.fans
    fan = graph.fans["fan"]
    assert fan.name == "fan"
    assert fan.pin == "PA8"
    assert fan.max_power is None


def test_fan_generic_part_cooling_section_parses() -> None:
    """``[fan_generic part_cooling]`` resolves to the documented id."""
    config = """
[fan_generic part_cooling]
pin: PA8
max_power: 0.5
"""
    graph = MachineConfigParser().parse_string(config)
    assert "fan_generic_part_cooling" in graph.fans
    fan = graph.fans["fan_generic_part_cooling"]
    assert fan.name == "fan_generic_part_cooling"
    assert fan.pin == "PA8"
    assert fan.max_power == pytest.approx(0.5)


def test_fan_without_pin_raises_missing_required_keyword() -> None:
    """A fan section without ``pin`` fails fast at parse time."""
    config = """
[fan]
max_power: 0.5
"""
    with pytest.raises(MissingRequiredKeywordError) as exc_info:
        MachineConfigParser().parse_string(config)
    assert exc_info.value.section == "fan"
    assert exc_info.value.key == "pin"


def test_fan_unknown_keyword_raises() -> None:
    """The strict schema rejects unsupported fan keys."""
    config = """
[fan]
pin: PA8
mystery: nope
"""
    with pytest.raises(UndefinedKeywordError) as exc_info:
        MachineConfigParser().parse_string(config)
    assert exc_info.value.section == "fan"
    assert exc_info.value.key == "mystery"


def test_fan_ignored_keys_logged_but_not_rejected() -> None:
    """``cycle_time`` / ``hardware_pwm`` / ``off_below`` are recognised
    but ignored; the parser still returns a clean :class:`Fan`.
    """
    config = """
[fan]
pin: PA8
cycle_time: 0.01
hardware_pwm: True
off_below: 0.1
"""
    graph = MachineConfigParser().parse_string(config)
    assert graph.fans["fan"].pin == "PA8"


def test_duplicate_fan_canonical_id_raises() -> None:
    """Identical fan section names raise configparser's DuplicateSectionError
    before our canonical-id check ever runs. The check is still wired
    (see ``_validate_fan_uniqueness``) and is exercised in tests that
    go around configparser via ``parse_string`` synthetic sections; we
    only assert the configparser-level guard here.
    """
    config = """
[fan_generic part_cooling]
pin: PA8

[fan_generic part_cooling]
pin: PB0
"""
    with pytest.raises(configparser.DuplicateSectionError):
        MachineConfigParser().parse_string(config)


# ---------------------------------------------------------------------- #
# Multi-MCU sections                                                      #
# ---------------------------------------------------------------------- #


def test_empty_mcu_defaults_to_remora_spi_and_octopus() -> None:
    """An empty ``[mcu]`` section defaults to the legacy single-MCU contract."""

    config = """
[mcu]
"""
    graph = MachineConfigParser().parse_string(config)
    assert "mcu" in graph.mcus
    mcu = graph.mcus["mcu"]
    assert mcu.connection == "remora-spi"
    assert mcu.interface is None
    assert mcu.board == "BIGTREETECH OCTOPUS"
    # Legacy back-compat property returns the same record.
    assert graph.mcu is mcu
    # ``hal_type`` collapses to the two-value discriminator the HAL
    # generator has always consumed.
    assert mcu.hal_type == "remora"


def test_named_mcu_section_keys_by_object_name() -> None:
    """``[mcu a]`` parses into ``graph.mcus["a"]`` with the right transport."""

    config = """
[mcu a]
connection: rs485
interface: com0
board: DELTA_FAKE
"""
    graph = MachineConfigParser().parse_string(config)
    assert "a" in graph.mcus
    mcu = graph.mcus["a"]
    assert mcu.connection == "rs485"
    assert mcu.interface == "com0"
    assert mcu.board == "DELTA_FAKE"
    assert mcu.hal_type == "parallel"


def test_multiple_mcus_coexist_in_mcus_dict() -> None:
    """Profiles may declare any number of ``[mcu]`` / ``[mcu NAME]``."""

    config = """
[mcu a]
connection: rs485
interface: com0

[mcu b]
connection: dummy

[mcu c]
connection: remora-spi
board: BIGTREETECH OCTOPUS

[mcu d]
connection: remora-eth
interface: 192.0.2.10
board: SKR2
"""
    graph = MachineConfigParser().parse_string(config)
    assert set(graph.mcus.keys()) == {"a", "b", "c", "d"}
    assert graph.mcus["a"].connection == "rs485"
    assert graph.mcus["b"].connection == "dummy"
    assert graph.mcus["c"].connection == "remora-spi"
    assert graph.mcus["d"].connection == "remora-eth"
    assert graph.mcus["d"].interface == "192.0.2.10"


def test_unknown_connection_raises_invalid_connection_error() -> None:
    """``connection: foo`` (not in ALLOWED_CONNECTION_TYPES) raises."""

    config = """
[mcu]
connection: dual_canbus
"""
    with pytest.raises(InvalidConnectionError) as exc_info:
        MachineConfigParser().parse_string(config)
    assert exc_info.value.section == "mcu"
    assert exc_info.value.key == "connection"
    assert exc_info.value.value == "dual_canbus"


def test_legacy_hal_type_keyword_rejected() -> None:
    """The pre-multi-MCU ``hal_type`` keyword is no longer valid."""

    config = """
[mcu]
hal_type: remora
"""
    with pytest.raises(UndefinedKeywordError) as exc_info:
        MachineConfigParser().parse_string(config)
    assert exc_info.value.section == "mcu"
    assert exc_info.value.key == "hal_type"


def test_legacy_serial_keyword_rejected() -> None:
    """Klipper's pre-multi-MCU ``serial`` / ``restart_method`` keys are gone."""

    config = """
[mcu]
serial: /dev/ttyACM0
restart_method: command
"""
    with pytest.raises(UndefinedKeywordError) as exc_info:
        MachineConfigParser().parse_string(config)
    assert exc_info.value.section == "mcu"
    assert exc_info.value.key in {"serial", "restart_method"}


def test_mcu_keywords_are_strict() -> None:
    """``MCU_KEYS`` is the enum-equivalent schema for the new section."""

    assert "connection" in MCU_KEYS
    assert "interface" in MCU_KEYS
    assert "board" in MCU_KEYS


def test_orphan_mcu_pin_qualifier_raises_undefined_mcu_error() -> None:
    """A ``mcu_missing:PF13`` pin reference must point at a declared section."""

    config = """
[mcu a]
connection: rs485
interface: com0

[stepper_x]
step_pin: missing_mcu:PF13
dir_pin: PA1
enable_pin: !PA2
rotation_distance: 40
microsteps: 16
"""
    with pytest.raises(UndefinedMcuError) as exc_info:
        MachineConfigParser().parse_string(config)
    # The section key on the graph is the axis letter ("x"), not the
    # Klipper section header ("stepper_x"); the error reports the
    # graph-side handle for cross-reference stability.
    assert exc_info.value.section == "x"
    assert exc_info.value.key == "step_pin"
    assert exc_info.value.mcu_name == "missing_mcu"
    assert "a" in exc_info.value.declared


def test_known_mcu_pin_qualifier_accepted() -> None:
    """A ``mcu_a:PF13`` qualifier that names a declared MCU is accepted."""

    config = """
[mcu a]
connection: rs485
interface: com0

[stepper_x]
step_pin: a:PF13
dir_pin: PA1
enable_pin: !PA2
rotation_distance: 40
microsteps: 16
"""
    graph = MachineConfigParser().parse_string(config)
    assert graph.mcus["a"].connection == "rs485"
    assert graph.steppers["x"].step_pin == "a:PF13"


def test_bare_pin_kept_verbatim_when_no_other_mcu_declared() -> None:
    """No qualifier + no second MCU = the pin is stored as-is for remora."""

    config = """
[mcu]
[stepper_x]
step_pin: PF11
dir_pin: PG3
enable_pin: !PG5
rotation_distance: 40
microsteps: 16
"""
    graph = MachineConfigParser().parse_string(config)
    assert graph.steppers["x"].step_pin == "PF11"


def test_dummy_mcu_accepts_arbitrary_pin_strings() -> None:
    """A ``[mcu dummy]`` connection is a placeholder; every pin form works."""

    config = """
[mcu dummy]
connection: dummy

[stepper_x]
step_pin: dummy:any.old.value
dir_pin: dummy:P0.0
enable_pin: !PA0
rotation_distance: 40
microsteps: 16
"""
    graph = MachineConfigParser().parse_string(config)
    assert graph.steppers["x"].step_pin == "dummy:any.old.value"
    assert graph.steppers["x"].dir_pin == "dummy:P0.0"
    assert graph.mcus["dummy"].connection == "dummy"


def test_split_pin_handles_bare_qualified_and_empty_inputs() -> None:
    """``split_pin`` is the canonical pin-qualifier parser."""

    assert split_pin("PF13") == (None, "PF13")
    assert split_pin("a:PF13") == ("a", "PF13")
    assert split_pin("rs485_com:RA") == ("rs485_com", "RA")
    assert split_pin(None) == (None, None)
    assert split_pin("") == (None, None)
    assert split_pin("a:") == ("a", None)
    assert split_pin(":PF13") == (None, "PF13")
