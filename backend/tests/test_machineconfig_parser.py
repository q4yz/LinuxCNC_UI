"""Tests for the strict Klipper configuration parser."""

from __future__ import annotations

import configparser

import pytest

from modules.machineconfig.models import EndstopSwitch, Extruder, Heater, Stepper
from modules.machineconfig.parser import (
    ConfigValidationError,
    DuplicateFanError,
    DuplicateHeaterError,
    DuplicateStepperPinError,
    MachineConfigParser,
    MissingRequiredKeywordError,
    MultipleExtrudersError,
    UndefinedKeywordError,
    UnknownStepperError,
    derive_fan_name,
    derive_heater_name,
)
from modules.machineconfig.schema import SectionKind, schema_for_section


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
serial: /dev/ttyACM0
restart_method: command

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

[spindle]
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
    assert machine.spindle is not None


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
