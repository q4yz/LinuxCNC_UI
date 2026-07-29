"""Strict parser that builds a linked machine-configuration object graph."""

from __future__ import annotations

import configparser
import logging
from io import StringIO
from pathlib import Path

from .models import (
    EndstopSwitch,
    Extruder,
    HeaterBed,
    MachineConfigGraph,
    MCU,
    Printer,
    Spindle,
    Stepper,
    TMC2209,
)
from .schema import PRINTER_IGNORED_KEYS, SectionKind, schema_for_section

logger = logging.getLogger("backend.modules.machineconfig.parser")


class ConfigValidationError(ValueError):
    """Base class for actionable machine-configuration errors."""


class UndefinedKeywordError(ConfigValidationError):
    """Raised as soon as a section contains a key outside its schema."""

    def __init__(self, section: str, key: str) -> None:
        self.section = section
        self.key = key
        super().__init__(f"Undefined keyword '{key}' in section [{section}]")


class UnsupportedSectionError(ConfigValidationError):
    """Raised when a profile declares a section the pipeline cannot model."""

    def __init__(self, section: str) -> None:
        self.section = section
        super().__init__(f"Unsupported configuration section [{section}]")


class MissingRequiredKeywordError(ConfigValidationError):
    """Raised when graph construction requires an absent or empty key."""

    def __init__(self, section: str, key: str) -> None:
        self.section = section
        self.key = key
        super().__init__(f"Missing required keyword '{key}' in section [{section}]")


class InvalidValueError(ConfigValidationError):
    """Raised when a listed keyword has a value of the wrong type or domain."""

    def __init__(self, section: str, key: str, value: str, expected: str) -> None:
        self.section = section
        self.key = key
        self.value = value
        self.expected = expected
        super().__init__(
            f"Invalid value '{value}' for '{key}' in section [{section}]; "
            f"expected {expected}"
        )


class UnknownStepperError(ConfigValidationError):
    """Raised when an endstop switch cannot link to its requested stepper."""

    def __init__(self, section: str, target: str) -> None:
        self.section = section
        self.target = target
        super().__init__(
            f"Section [{section}] references unknown stepper '{target}'"
        )


class MachineConfigParser:
    """Parse a Klipper-style INI file into a strict dataclass graph.

    The source may be supplied at construction or to :meth:`parse`. Supplying
    it to :meth:`parse` makes one parser instance reusable without retaining
    any state from the previous profile.
    """

    def __init__(self, source_path: str | Path | None = None) -> None:
        self.source_path = Path(source_path) if source_path is not None else None

    def parse(self, source_path: str | Path | None = None) -> MachineConfigGraph:
        """Read ``source_path``, validate it, and return its linked graph."""

        path = Path(source_path) if source_path is not None else self.source_path
        if path is None:
            raise ValueError("A configuration source path is required")
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"Configuration file not found: {path}")

        parser = self._new_ini_parser()
        with path.open("r", encoding="utf-8") as handle:
            parser.read_file(handle, source=str(path))
        return self._build_graph(parser)

    def parse_string(
        self,
        content: str,
        *,
        source: str = "<string>",
    ) -> MachineConfigGraph:
        """Validate in-memory configuration text; useful for API/tests."""

        parser = self._new_ini_parser()
        parser.read_file(StringIO(content), source=source)
        return self._build_graph(parser)

    @staticmethod
    def _new_ini_parser() -> configparser.ConfigParser:
        parser = configparser.ConfigParser(
            interpolation=None,
            inline_comment_prefixes=("#", ";"),
            empty_lines_in_values=False,
            strict=True,
        )
        # Klipper's PID names use a capital K (pid_Kp/Ki/Kd). Preserving case
        # lets the schema reject misspellings instead of silently normalising.
        parser.optionxform = str
        return parser

    def _build_graph(self, parser: configparser.ConfigParser) -> MachineConfigGraph:
        graph = MachineConfigGraph()
        pending_endstops: list[tuple[str, str, configparser.SectionProxy]] = []

        for section_name in parser.sections():
            section_schema = schema_for_section(section_name)
            if section_schema is None:
                raise UnsupportedSectionError(section_name)

            section = parser[section_name]
            self._validate_keywords(section_name, section, section_schema.allowed_keys)

            if section_schema.kind is SectionKind.MCU:
                # MCU sections are mostly ignored for LinuxCNC, but we
                # extract ``hal_type`` so the HAL generator can switch
                # between Remora and parallel templates.
                graph.mcu = self._parse_mcu(section_name, section)
                logger.info(
                    "Bypassing [%s]: Klipper MCU transport settings are ignored for LinuxCNC (hal_type=%s)",
                    section_name,
                    graph.mcu.hal_type if graph.mcu else "remora",
                )
                continue

            object_name = section_schema.object_name
            if object_name is None:  # Defensive: all modelled schemas have a name.
                raise UnsupportedSectionError(section_name)

            if section_schema.kind is SectionKind.PRINTER:
                graph.printer = self._parse_printer(section_name, section)
            elif section_schema.kind is SectionKind.STEPPER:
                graph.steppers[object_name] = self._parse_stepper(
                    object_name,
                    section_name,
                    section,
                )
            elif section_schema.kind is SectionKind.ENDSTOP_SWITCH:
                pending_endstops.append((object_name, section_name, section))
            elif section_schema.kind is SectionKind.EXTRUDER:
                graph.extruder = self._parse_extruder(section_name, section)
            elif section_schema.kind is SectionKind.HEATER_BED:
                graph.heater_bed = self._parse_heater_bed(section_name, section)
            elif section_schema.kind is SectionKind.SPINDLE:
                graph.spindle = self._parse_spindle(section_name, section)
            elif section_schema.kind is SectionKind.TMC2209:
                graph.tmc2209s[object_name] = self._parse_tmc2209(
                    object_name,
                    section_name,
                    section,
                )

        # Resolve after all sections are parsed so an endstop may appear before
        # its target stepper in the source file.
        for name, section_name, section in pending_endstops:
            target = self._required_string(section_name, section, "stepper")
            stepper = graph.find_stepper(target)
            if stepper is None:
                raise UnknownStepperError(section_name, target)
            switch = self._parse_endstop(name, section_name, section, stepper)
            graph.endstop_switches[name] = switch
            stepper.endstops.append(switch)

        return graph

    @staticmethod
    def _validate_keywords(
        section_name: str,
        section: configparser.SectionProxy,
        allowed_keys: frozenset[str] | None,
    ) -> None:
        # MCU sections are explicitly ignored and therefore bypass key checks.
        if allowed_keys is None:
            return
        for key in section:
            if key not in allowed_keys:
                raise UndefinedKeywordError(section_name, key)

    def _parse_printer(
        self,
        section_name: str,
        section: configparser.SectionProxy,
    ) -> Printer:
        for key in PRINTER_IGNORED_KEYS:
            if key in section:
                logger.info(
                    "Ignoring [%s] %s: it has no LinuxCNC equivalent",
                    section_name,
                    key,
                )

        kinematics = self._optional_string(section, "kinematics") or "cartesian"
        if kinematics != "cartesian":
            raise InvalidValueError(
                section_name,
                "kinematics",
                kinematics,
                "'cartesian'",
            )
        return Printer(
            kinematics="cartesian",
            max_velocity=self._optional_float(section_name, section, "max_velocity"),
            max_accel=self._optional_float(section_name, section, "max_accel"),
        )

    def _parse_stepper(
        self,
        axis: str,
        section_name: str,
        section: configparser.SectionProxy,
    ) -> Stepper:
        return Stepper(
            axis=axis,
            step_pin=self._optional_string(section, "step_pin"),
            dir_pin=self._optional_string(section, "dir_pin"),
            enable_pin=self._optional_string(section, "enable_pin"),
            rotation_distance=self._optional_float(
                section_name, section, "rotation_distance"
            ),
            microsteps=self._optional_int(section_name, section, "microsteps"),
            endstop_pin=self._optional_string(section, "endstop_pin"),
            position_endstop=self._optional_float(
                section_name, section, "position_endstop"
            ),
            position_max=self._optional_float(section_name, section, "position_max"),
        )

    def _parse_endstop(
        self,
        name: str,
        section_name: str,
        section: configparser.SectionProxy,
        stepper: Stepper,
    ) -> EndstopSwitch:
        switch_type = self._optional_string(section, "type") or "limit"
        if switch_type not in {"limit", "trigger"}:
            raise InvalidValueError(
                section_name,
                "type",
                switch_type,
                "'limit' or 'trigger'",
            )
        return EndstopSwitch(
            name=name,
            stepper=stepper,
            pin=self._optional_string(section, "pin"),
            position=self._optional_float(section_name, section, "position"),
            type=switch_type,
        )

    def _parse_extruder(
        self,
        section_name: str,
        section: configparser.SectionProxy,
    ) -> Extruder:
        return Extruder(
            step_pin=self._optional_string(section, "step_pin"),
            dir_pin=self._optional_string(section, "dir_pin"),
            enable_pin=self._optional_string(section, "enable_pin"),
            microsteps=self._optional_int(section_name, section, "microsteps"),
            rotation_distance=self._optional_float(
                section_name, section, "rotation_distance"
            ),
            nozzle_diameter=self._optional_float(
                section_name, section, "nozzle_diameter"
            ),
            filament_diameter=self._optional_float(
                section_name, section, "filament_diameter"
            ),
            heater_pin=self._optional_string(section, "heater_pin"),
            sensor_type=self._optional_string(section, "sensor_type"),
            sensor_pin=self._optional_string(section, "sensor_pin"),
            control=self._optional_string(section, "control"),
            pid_Kp=self._optional_float(section_name, section, "pid_Kp"),
            pid_Ki=self._optional_float(section_name, section, "pid_Ki"),
            pid_Kd=self._optional_float(section_name, section, "pid_Kd"),
            min_temp=self._optional_float(section_name, section, "min_temp"),
            max_temp=self._optional_float(section_name, section, "max_temp"),
        )

    def _parse_heater_bed(
        self,
        section_name: str,
        section: configparser.SectionProxy,
    ) -> HeaterBed:
        return HeaterBed(
            heater_pin=self._optional_string(section, "heater_pin"),
            sensor_type=self._optional_string(section, "sensor_type"),
            sensor_pin=self._optional_string(section, "sensor_pin"),
            control=self._optional_string(section, "control"),
            min_temp=self._optional_float(section_name, section, "min_temp"),
            max_temp=self._optional_float(section_name, section, "max_temp"),
        )

    def _parse_spindle(
        self,
        section_name: str,
        section: configparser.SectionProxy,
    ) -> Spindle:
        return Spindle(
            pwm_pin=self._optional_string(section, "pwm_pin"),
            enable_pin=self._optional_string(section, "enable_pin"),
            max_rpm=self._optional_float(section_name, section, "max_rpm"),
        )

    def _parse_mcu(
        self,
        section_name: str,
        section: configparser.SectionProxy,
    ) -> MCU:
        return MCU(
            hal_type=self._optional_string(section, "hal_type") or "remora",
        )

    def _parse_tmc2209(
        self,
        stepper: str,
        section_name: str,
        section: configparser.SectionProxy,
    ) -> TMC2209:
        return TMC2209(
            stepper=stepper,
            uart_pin=self._optional_string(section, "uart_pin"),
            run_current=self._optional_float(section_name, section, "run_current"),
            stealthchop_threshold=self._optional_int(
                section_name, section, "stealthchop_threshold"
            ),
            microsteps=self._optional_int(section_name, section, "microsteps"),
            interpolate=self._optional_bool(section, "interpolate"),
            hold_current=self._optional_float(section_name, section, "hold_current"),
            sense_resistor=self._optional_float(section_name, section, "sense_resistor"),
        )

    @staticmethod
    def _optional_string(
        section: configparser.SectionProxy,
        key: str,
    ) -> str | None:
        if key not in section:
            return None
        value = section[key].strip()
        return value or None

    def _required_string(
        self,
        section_name: str,
        section: configparser.SectionProxy,
        key: str,
    ) -> str:
        value = self._optional_string(section, key)
        if value is None:
            raise MissingRequiredKeywordError(section_name, key)
        return value

    def _optional_float(
        self,
        section_name: str,
        section: configparser.SectionProxy,
        key: str,
    ) -> float | None:
        value = self._optional_string(section, key)
        if value is None:
            return None
        try:
            return float(value)
        except ValueError as exc:
            raise InvalidValueError(section_name, key, value, "a number") from exc

    def _optional_int(
        self,
        section_name: str,
        section: configparser.SectionProxy,
        key: str,
    ) -> int | None:
        value = self._optional_string(section, key)
        if value is None:
            return None
        try:
            return int(value)
        except ValueError as exc:
            raise InvalidValueError(section_name, key, value, "an integer") from exc

    @staticmethod
    def _optional_bool(
        section: configparser.SectionProxy,
        key: str,
    ) -> bool | None:
        if key not in section:
            return None
        value = section[key].strip().lower()
        if value in {"true", "yes", "on", "1"}:
            return True
        if value in {"false", "no", "off", "0"}:
            return False
        return None


# Descriptive alias for clients that refer to the input dialect explicitly.
KlipperConfigParser = MachineConfigParser


def parse_config(source_path: str | Path) -> MachineConfigGraph:
    """Parse ``source_path`` using :class:`MachineConfigParser`."""

    return MachineConfigParser(source_path).parse()


__all__ = [
    "ConfigValidationError",
    "InvalidValueError",
    "KlipperConfigParser",
    "MachineConfigParser",
    "MissingRequiredKeywordError",
    "UndefinedKeywordError",
    "UnknownStepperError",
    "UnsupportedSectionError",
    "parse_config",
]
