"""Strict parser that builds a linked machine-configuration object graph."""

from __future__ import annotations

import configparser
import logging
from io import StringIO
from pathlib import Path

from .models import (
    EndstopSwitch,
    Extruder,
    Fan,
    Heater,
    MachineConfigGraph,
    MCU,
    Printer,
    SpindleAnalog,
    SpindleDigital,
    Stepper,
    TMC2209,
)
from .schema import (
    ALLOWED_CONNECTION_TYPES,
    EXTRUDER_KEYS,
    FAN_IGNORED_KEYS,
    HEATER_KEYS,
    PRINTER_IGNORED_KEYS,
    SectionKind,
    schema_for_section,
)

logger = logging.getLogger("backend.modules.machineconfig.parser")


class ConfigValidationError(ValueError):
    """Base class for actionable machine-configuration errors.

    Each subclass carries a :attr:`kind` discriminator (used by the
    HTTP layer to populate the structured error response) and a
    :meth:`to_dict` serializer that the FastAPI exception handler
    forwards verbatim to the frontend toast channel.
    """

    #: Stable error discriminator. Subclasses MUST override.
    kind: str = "config_validation_error"

    #: Optional source line. Default ``None`` — configparser does not
    #: expose line numbers for value-level errors in this version, but
    #: the slot is reserved so a future tokenizer upgrade can populate
    #: it without changing the response shape.
    line: int | None = None

    #: Affected section name (where applicable). ``None`` when the
    #: error is global (e.g. an unsupported top-level section).
    section: str | None = None

    #: Affected key within ``section`` (where applicable). ``None``
    #: when the error spans the whole section.
    key: str | None = None

    def to_dict(self) -> dict:
        """Return the structured representation the HTTP layer ships.

        The shape is the contract surface for the frontend toast
        channel (see issue #99). Adding a field here is safe; removing
        or renaming a field is a breaking change.
        """

        return {
            "section": self.section,
            "key": self.key,
            "line": self.line,
            "message": str(self),
            "kind": self.kind,
        }


class UndefinedKeywordError(ConfigValidationError):
    """Raised as soon as a section contains a key outside its schema."""

    kind = "undefined_keyword"

    def __init__(self, section: str, key: str, line: int | None = None) -> None:
        self.section = section
        self.key = key
        self.line = line
        super().__init__(f"Undefined keyword '{key}' in section [{section}]")


class UnsupportedSectionError(ConfigValidationError):
    """Raised when a profile declares a section the pipeline cannot model."""

    kind = "unsupported_section"

    def __init__(self, section: str, line: int | None = None) -> None:
        self.section = section
        self.line = line
        super().__init__(f"Unsupported configuration section [{section}]")


class MissingRequiredKeywordError(ConfigValidationError):
    """Raised when graph construction requires an absent or empty key.

    The ``key`` argument is either a single keyword (string) or a
    list of keywords that are all missing together. The list form
    is used when one validation pass detects multiple missing keys
    (e.g. the heater-field validator that requires
    ``heater_pin`` + ``sensor_pin`` + ``control``).
    """

    kind = "missing_required_keyword"

    def __init__(self, section: str, key: str | list[str], line: int | None = None) -> None:
        self.section = section
        self.key = key
        self.line = line
        if isinstance(key, list):
            joined = ", ".join(key)
            super().__init__(
                f"Missing required keyword(s) '{joined}' in section [{section}]"
            )
        else:
            super().__init__(f"Missing required keyword '{key}' in section [{section}]")


class InvalidValueError(ConfigValidationError):
    """Raised when a listed keyword has a value of the wrong type or domain."""

    kind = "invalid_value"

    def __init__(
        self,
        section: str,
        key: str,
        value: str,
        expected: str,
        line: int | None = None,
    ) -> None:
        self.section = section
        self.key = key
        self.value = value
        self.expected = expected
        self.line = line
        super().__init__(
            f"Invalid value '{value}' for '{key}' in section [{section}]; "
            f"expected {expected}"
        )


class UnknownStepperError(ConfigValidationError):
    """Raised when an endstop switch cannot link to its requested stepper."""

    kind = "unknown_stepper"

    def __init__(self, section: str, target: str, line: int | None = None) -> None:
        self.section = section
        self.key = target
        self.target = target
        self.line = line
        super().__init__(
            f"Section [{section}] references unknown stepper '{target}'"
        )


class MultipleExtrudersError(ConfigValidationError):
    """Raised when more than one bare ``[extruder]`` section is declared."""

    kind = "multiple_extruders"

    def __init__(self, sections: list[str]) -> None:
        self.sections = sections
        joined = ", ".join(f"[{name}]" for name in sections)
        super().__init__(
            f"At most one bare [extruder] section is allowed; "
            f"found multiple: {joined}. Use named extruders "
            f"([extruder my_name]) or numbered extruders ([extruder1]) "
            f"for additional tools."
        )


class DuplicateHeaterError(ConfigValidationError):
    """Raised when two sections resolve to the same canonical heater name."""

    kind = "duplicate_heater"

    def __init__(self, section_a: str, section_b: str, name: str) -> None:
        self.section_a = section_a
        self.section_b = section_b
        self.name = name
        super().__init__(
            f"Sections [{section_a}] and [{section_b}] both compile to "
            f"the same heater name '{name}'. The numbered and spaced "
            f"extruder forms are equivalent — pick one."
        )


class DuplicateFanError(ConfigValidationError):
    """Raised when two fan sections resolve to the same canonical id."""

    kind = "duplicate_fan"

    def __init__(self, section_a: str, section_b: str, name: str) -> None:
        self.section_a = section_a
        self.section_b = section_b
        self.name = name
        super().__init__(
            f"Sections [{section_a}] and [{section_b}] both compile to "
            f"the same fan name '{name}'."
        )


class DuplicateSpindleError(ConfigValidationError):
    """Raised when two digital-spindle sections resolve to the same canonical id.

    Mirrors :class:`DuplicateFanError`. Two sections like ``[spindle]``
    and ``[spindle ]`` (or ``[spindle test]`` and ``[spindle test]``)
    would both resolve to the same id; the parser rejects that so
    downstream tool records do not collide.
    """

    kind = "duplicate_spindle"

    def __init__(self, section_a: str, section_b: str, name: str) -> None:
        self.section_a = section_a
        self.section_b = section_b
        self.name = name
        super().__init__(
            f"Sections [{section_a}] and [{section_b}] both compile to "
            f"the same spindle id '{name}'."
        )


class DuplicateStepperPinError(ConfigValidationError):
    """Raised when two distinct stepper sections share a physical pin.

    Two axes cannot drive the same physical pin — LinuxCNC's HAL
    would silently override the second assignment and the operator
    would see one motor hold position while the other runs away.
    Catching it at compile time is the contract the issue imposes.
    """

    kind = "duplicate_stepper_pin"

    def __init__(
        self,
        section: str,
        pin_key: str,
        pin: str,
        axes: list[str],
        line: int | None = None,
    ) -> None:
        # ``section`` is the section the duplicate was found in; the
        # first axis that claimed the pin is reported in ``axes[0]``.
        # ``pin_key`` is the schema key the conflict lives under
        # (e.g. ``step_pin``, ``dir_pin``, ``enable_pin``,
        # ``endstop_pin``).
        self.section = section
        self.key = pin_key
        self.pin_key = pin_key
        self.pin = pin
        self.axes = list(axes)
        self.line = line
        axes_label = "axes" if len(axes) > 2 else "axes"
        super().__init__(
            f"Duplicate stepper pin '{pin}' on '{pin_key}' between "
            f"{axes_label} {', '.join(repr(axis) for axis in axes)}"
        )


class InvalidConnectionError(ConfigValidationError):
    """Raised when an MCU's ``connection`` keyword is not in the enum."""

    kind = "invalid_connection"

    def __init__(
        self,
        section: str,
        value: str,
        allowed: frozenset[str] | list[str] | tuple[str, ...],
    ) -> None:
        self.section = section
        self.key = "connection"
        self.value = value
        self.allowed = sorted(allowed)
        super().__init__(
            f"Invalid value '{value}' for 'connection' in section "
            f"[{section}]; expected one of {self.allowed}"
        )


class UndefinedMcuError(ConfigValidationError):
    """Raised when a pin reference names an MCU that wasn't declared.

    Klipper multi-MCU syntax lets a stepper / heater / fan / endstop
    pin be prefixed with the target MCU's name (``a:PF13``). The
    parser enforces that the prefix matches a section actually
    declared in the same profile, because a typo would otherwise
    silently route a pin onto a board that wasn't built.

    The diagnostic names both the missing MCU and the section /
    keyword the orphan pin lives under so the operator can locate
    it in the editor.
    """

    kind = "undefined_mcu"

    def __init__(
        self,
        section: str,
        key: str,
        mcu_name: str,
        declared: list[str] | tuple[str, ...],
    ) -> None:
        self.section = section
        self.key = key
        self.mcu_name = mcu_name
        self.declared = list(declared)
        super().__init__(
            f"Section [{section}] references unknown MCU '{mcu_name}' "
            f"in '{key}'. Declared MCUs: {self.declared}"
        )


class DuplicateMcuSectionError(ConfigValidationError):
    """Raised when two sections resolve to the same MCU object name.

    The schema regex guarantees one section per name; two distinct
    sections like ``[mcu]`` and ``[mcu mcu]`` would both resolve to
    ``"mcu"``. The parser rejects that with the diagnostic naming
    the two source section headers so the operator can rename one.
    """

    kind = "duplicate_mcu"

    def __init__(self, section_a: str, section_b: str, name: str) -> None:
        self.section_a = section_a
        self.section_b = section_b
        self.name = name
        super().__init__(
            f"Sections [{section_a}] and [{section_b}] both declare "
            f"MCU '{name}'. Rename one."
        )


def split_pin(pin: str | None) -> tuple[str | None, str | None]:
    """Split a Klipper multi-MCU pin reference into ``(mcu_name, raw)``.

    Klipper syntax lets a pin be qualified with an MCU prefix::

        step_pin: PF13            -> (None, 'PF13')
        step_pin: a:PF13          -> ('a', 'PF13')
        step_pin: rs485_com:RA    -> ('rs485_com', 'RA')

    Returns ``(None, None)`` for a falsy input so callers can chain
    ``if pin is None`` checks without special-casing the empty
    string. The split is strictly on the *first* colon — subsequent
    colons are part of the raw pin (none of Klipper's standard pin
    formats contain a colon, but the convention keeps us future-safe).
    """
    if pin is None:
        return (None, None)
    text = pin.strip()
    if not text:
        return (None, None)
    if ":" not in text:
        return (None, text)
    mcu_part, _, rest = text.partition(":")
    mcu_part = mcu_part.strip() or None
    rest = rest.strip() or None
    return (mcu_part, rest)


# Heater-shaped sections ALL must carry these three physical fields.
# Stepper fields are optional for extruders (some toolheads declare
# them on a separate ``[stepper_*]`` section); the heater fields are
# what make the section a heater at all.
_HEATER_REQUIRED_KEYS = ("heater_pin", "sensor_pin", "control")
# When control is "pid", these three are also required.
_PID_REQUIRED_KEYS = ("pid_Kp", "pid_Ki", "pid_Kd")


def derive_heater_name(section_name: str) -> str:
    """Return the canonical heater name for a Klipper section header.

    Examples:
        [extruder]               -> "extruder"
        [extruder 1]             -> "extruder_1"
        [extruder1]              -> "extruder_1"   (Klipper compatibility)
        [extruder hotend]        -> "extruder_hotend"
        [heater_bed]             -> "heater_bed"
        [heater_generic]         -> "heater_generic"
        [heater_generic chamber] -> "heater_generic_chamber"

    The ``[extruder<N>]`` form is accepted only for Klipper parser
    compatibility; downstream code sees only the normalised
    ``extruder_<N>`` form produced by this helper.
    """
    # Normalise [extruder<N>] -> [extruder <N>] so the split below
    # handles both forms identically. Only the extruder section kind
    # has this dual syntax in Klipper; heater_* sections do not.
    if section_name.startswith("extruder") and len(section_name) > len("extruder"):
        rest = section_name[len("extruder"):]
        if rest and rest[0].isdigit():
            section_name = f"extruder {rest}"

    parts = section_name.split(maxsplit=1)
    if len(parts) == 1:
        return section_name
    kind, instance = parts
    return f"{kind}_{instance.replace(' ', '_')}"


def derive_fan_name(section_name: str) -> str:
    """Return the canonical fan id for a Klipper section header.

    Examples:
        [fan]                    -> "fan"
        [fan_generic]            -> "fan_generic"
        [fan_generic part_cooling] -> "fan_generic_part_cooling"

    Mirrors :func:`derive_heater_name` so the fan and heater id
    namespaces stay uniform (``[foo bar]`` -> ``"foo_bar"``).
    """
    parts = section_name.split(maxsplit=1)
    if len(parts) == 1:
        return section_name
    kind, instance = parts
    return f"{kind}_{instance.replace(' ', '_')}"


def derive_spindle_name(section_name: str) -> str:
    """Return the canonical digital-spindle id for a Klipper section header.

    Examples:
        [spindle]            -> "spindle_digital"
        [spindle test]       -> "spindle_digital_test"
        [spindle mill_h]     -> "spindle_digital_mill_h"

    The bare ``[spindle]`` form maps to ``"spindle_digital"`` (not
    ``"spindle"``) so the canonical id is distinct from the section
    header — the runtime vocabulary uses ``"spindle_digital"`` as the
    ``type`` discriminator in ``hardware.json`` and operators never
    see a bare ``"spindle"`` id on the frontend.
    """
    parts = section_name.split(maxsplit=1)
    if len(parts) == 1:
        return "spindle_digital"
    kind, instance = parts
    return f"spindle_digital_{instance.replace(' ', '_')}"


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
        with path.open(encoding="utf-8") as handle:
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
        # Order in which heater-shaped sections appear in the source file.
        # Used at the end for duplicate-name detection so the error
        # message points at the second occurrence rather than the first.
        heater_section_order: list[str] = []
        # Order in which fan-shaped sections appear in the source file.
        # Same rationale as ``heater_section_order``.
        fan_section_order: list[str] = []
        # Order in which digital-spindle sections appear in the source
        # file. Same rationale as ``heater_section_order`` — used for
        # duplicate-id detection in ``_validate_spindle_uniqueness``.
        spindle_section_order: list[str] = []

        for section_name in parser.sections():
            section_schema = schema_for_section(section_name)
            if section_schema is None:
                raise UnsupportedSectionError(section_name)

            section = parser[section_name]
            self._validate_keywords(section_name, section, section_schema.allowed_keys)

            if section_schema.kind is SectionKind.MCU:
                mcu = self._parse_mcu(section_name, section)
                if section_schema.object_name in graph.mcus:
                    existing_section = _find_section_name_for_mcu(
                        section_schema.object_name,
                        graph.mcus,
                    )
                    raise DuplicateMcuSectionError(
                        existing_section or section_name,
                        section_name,
                        section_schema.object_name,
                    )
                graph.mcus[section_schema.object_name] = mcu
                continue

            if section_schema.kind is SectionKind.PRINTER:
                graph.printer = self._parse_printer(section_name, section)
            elif section_schema.kind is SectionKind.STEPPER:
                graph.steppers[section_schema.object_name] = self._parse_stepper(
                    section_schema.object_name,
                    section_name,
                    section,
                )
            elif section_schema.kind is SectionKind.ENDSTOP_SWITCH:
                pending_endstops.append(
                    (section_schema.object_name, section_name, section)
                )
            elif section_schema.kind is SectionKind.EXTRUDER:
                self._validate_heater_fields(section_name, section)
                self._validate_pid_keys_if_pid(section_name, section)
                heater = self._parse_extruder(section_name, section)
                heater_section_order.append(section_name)
                graph.heaters[heater.name] = heater
            elif section_schema.kind is SectionKind.HEATER:
                self._validate_heater_fields(section_name, section)
                self._validate_pid_keys_if_pid(section_name, section)
                heater = self._parse_heater(section_name, section)
                heater_section_order.append(section_name)
                graph.heaters[heater.name] = heater
            elif section_schema.kind is SectionKind.SPINDLE:
                spindle = self._parse_spindle_digital(section_name, section)
                spindle_id = derive_spindle_name(section_name)
                graph.spindle_digitals[spindle_id] = spindle
                spindle_section_order.append(section_name)
            elif section_schema.kind is SectionKind.SPINDLE_ANALOG:
                graph.spindle_analog = self._parse_spindle_analog(
                    section_name, section
                )
            elif section_schema.kind is SectionKind.TMC2209:
                graph.tmc2209s[section_schema.object_name] = self._parse_tmc2209(
                    section_schema.object_name,
                    section_name,
                    section,
                )
            elif section_schema.kind is SectionKind.FAN:
                fan = self._parse_fan(section_name, section)
                graph.fans[fan.name] = fan
                fan_section_order.append(section_name)

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

        # Post-parse validation runs after the graph is fully built so
        # every stepper's pins and every heater's name are known.
        # Both validations are cheap and produce structured errors.
        self._validate_heater_uniqueness(graph, heater_section_order)
        self._validate_fan_uniqueness(graph, fan_section_order)
        self._validate_spindle_uniqueness(spindle_section_order)
        self._validate_stepper_pins(graph)
        self._validate_all_pin_mcu_references(graph)

        return graph

    @staticmethod
    def _validate_stepper_pins(graph: MachineConfigGraph) -> None:
        """Reject steppers that share any physical pin.

        Walks ``graph.steppers`` and tracks the first section that
        claimed each pin across the four pin slots
        (:attr:`Stepper.step_pin`, :attr:`Stepper.dir_pin`,
        :attr:`Stepper.enable_pin`, :attr:`Stepper.endstop_pin`).
        A second stepper claiming the same pin raises
        :class:`DuplicateStepperPinError` with the offending pin,
        pin-key, and the two conflicting axes.

        The check intentionally ignores ``None`` values (an unset pin
        is fine) and the extruder's own pins (extruders live on a
        different pin domain and do not participate in the stepper
        collision matrix). Multiple motors on one axis (e.g.
        ``[stepper_y]`` + ``[stepper_y1]``) must use distinct pins;
        the parser is the right place to enforce that.
        """

        pin_slots: tuple[str, str] = (
            ("step_pin", "step_pin"),
            ("dir_pin", "dir_pin"),
            ("enable_pin", "enable_pin"),
            ("endstop_pin", "endstop_pin"),
        )
        # ``owners`` maps ``(pin_key, mcu_prefix, pin_value)`` ->
        # ``(axis_label, section_name)``. The MCU prefix is the
        # Klipper multi-MCU qualifier (``mcu_a:PF13`` -> ``"mcu_a"``,
        # bare ``PF13`` -> ``None``). Two steppers that share the same
        # raw pin string but address different transports (e.g.
        # one on the remora MCU, one on an RS-485 companion) are
        # therefore not flagged as duplicates — only same-prefix
        # collisions trigger the error.
        owners: dict[tuple[str, str | None, str], tuple[str, str]] = {}

        for section_name, stepper in graph.steppers.items():
            for attr_name, pin_key in pin_slots:
                pin_value = getattr(stepper, attr_name, None)
                if not pin_value:
                    continue
                mcu_prefix, raw_pin = split_pin(pin_value)
                if raw_pin is None:
                    continue
                key = (pin_key, mcu_prefix, raw_pin)
                existing = owners.get(key)
                if existing is not None:
                    prior_axis, _ = existing
                    raise DuplicateStepperPinError(
                        section=section_name,
                        pin_key=pin_key,
                        pin=pin_value,
                        axes=[prior_axis, stepper.axis],
                    )
                owners[key] = (stepper.axis, section_name)

    @staticmethod
    def _validate_keywords(
        section_name: str,
        section: configparser.SectionProxy,
        allowed_keys: frozenset[str] | None,
    ) -> None:
        if allowed_keys is None:
            return
        for key in section:
            if key not in allowed_keys:
                raise UndefinedKeywordError(section_name, key)

    @staticmethod
    def _validate_heater_fields(
        section_name: str,
        section: configparser.SectionProxy,
    ) -> None:
        """Every heater-shaped section must declare heater_pin, sensor_pin, control."""
        missing = [
            key for key in _HEATER_REQUIRED_KEYS if not _option_present(section, key)
        ]
        if missing:
            raise MissingRequiredKeywordError(section_name, missing)

    @staticmethod
    def _validate_pid_keys_if_pid(
        section_name: str,
        section: configparser.SectionProxy,
    ) -> None:
        """When ``control`` is ``pid``, the three pid_* keys are mandatory."""
        control = _option_stripped(section, "control")
        if control is None or control.lower() != "pid":
            return
        missing = [
            key for key in _PID_REQUIRED_KEYS if not _option_present(section, key)
        ]
        if missing:
            raise MissingRequiredKeywordError(section_name, missing)

    @staticmethod
    def _validate_heater_uniqueness(
        graph: MachineConfigGraph,
        heater_section_order: list[str],
    ) -> None:
        """Enforce two rules after all sections are parsed:

        1. At most one bare ``[extruder]`` section may exist. Bare
           extruders are the no-suffix form; numbered and named
           extruders are always allowed.
        2. No two sections may resolve to the same canonical heater
           name (catches ``[extruder 1]`` + ``[extruder1]``).
        """
        # Rule 1: multiple bare extruders.
        bare_extruders = [
            name for name in heater_section_order
            if name == "extruder"
        ]
        if len(bare_extruders) > 1:
            raise MultipleExtrudersError(bare_extruders)

        # Rule 2: duplicate canonical heater names. Walk in source
        # order so the error points at the second occurrence.
        seen: dict[str, str] = {}
        for section_name in heater_section_order:
            canonical = derive_heater_name(section_name)
            if canonical in seen:
                raise DuplicateHeaterError(seen[canonical], section_name, canonical)
            seen[canonical] = section_name

    @staticmethod
    def _validate_fan_uniqueness(
        graph: MachineConfigGraph,
        fan_section_order: list[str],
    ) -> None:
        """Reject two fan sections that resolve to the same canonical id.

        Mirrors :meth:`_validate_heater_uniqueness` for the fan list.
        Duplicate canonical ids would produce duplicate ``hardware.json``
        records; the parser is the right place to enforce that.
        """
        seen: dict[str, str] = {}
        for section_name in fan_section_order:
            canonical = derive_fan_name(section_name)
            if canonical in seen:
                raise DuplicateFanError(
                    seen[canonical], section_name, canonical
                )
            seen[canonical] = section_name

    @staticmethod
    def _validate_spindle_uniqueness(spindle_section_order: list[str]) -> None:
        """Reject two digital-spindle sections that resolve to the same id.

        Mirrors :meth:`_validate_fan_uniqueness`. Two distinct section
        headers (e.g. ``[spindle]`` and ``[spindle]`` in different
        positions, or ``[spindle test]`` declared twice) would both
        resolve to ``"spindle_digital_test"``; the parser rejects that
        so the runtime never sees two tool records with the same id.
        """
        seen: dict[str, str] = {}
        for section_name in spindle_section_order:
            canonical = derive_spindle_name(section_name)
            if canonical in seen:
                raise DuplicateSpindleError(
                    seen[canonical], section_name, canonical
                )
            seen[canonical] = section_name

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
            name=derive_heater_name(section_name),
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

    def _parse_heater(
        self,
        section_name: str,
        section: configparser.SectionProxy,
    ) -> Heater:
        """Parse a non-extruder heater section (``[heater_bed]``,
        ``[heater_generic]``, ``[heater_generic chamber]``)."""
        return Heater(
            name=derive_heater_name(section_name),
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

    def _parse_spindle_analog(
        self,
        section_name: str,
        section: configparser.SectionProxy,
    ) -> SpindleAnalog:
        return SpindleAnalog(
            pwm_pin=self._optional_string(section, "pwm_pin"),
            enable_pin=self._optional_string(section, "enable_pin"),
            max_rpm=self._optional_float(section_name, section, "max_rpm"),
            min_rpm=self._optional_float(section_name, section, "min_rpm"),
        )

    def _parse_spindle_digital(
        self,
        section_name: str,
        section: configparser.SectionProxy,
    ) -> SpindleDigital:
        return SpindleDigital(
            max_rpm=self._optional_float(section_name, section, "max_rpm"),
            min_rpm=self._optional_float(section_name, section, "min_rpm"),
            target_rpm_signal=self._optional_string(section, "target_rpm_signal"),
            target_frequency_signal=self._optional_string(
                section, "target_frequency_signal"
            ),
            rpm_out_signal=self._optional_string(section, "rpm_out_signal"),
            at_speed1_signal=self._optional_string(section, "at_speed1_signal"),
            at_speed2_signal=self._optional_string(section, "at_speed2_signal"),
            is_connected_signal=self._optional_string(section, "is_connected_signal"),
            error_count_signal=self._optional_string(section, "error_count_signal"),
            last_error_signal=self._optional_string(section, "last_error_signal"),
        )

    def _parse_mcu(
        self,
        section_name: str,
        section: configparser.SectionProxy,
    ) -> MCU:
        """Build an :class:`MCU` from an ``[mcu NAME]`` section.

        The defaults preserve the historical single-MCU flow:

        * ``connection`` defaults to ``"remora-spi"``.
        * ``board`` defaults to ``"BIGTREETECH OCTOPUS"`` so a
          back-compat empty ``[mcu]`` produces the same
          ``config.txt`` it did before this section became
          first-class (the snapshot test relies on it).
        """
        connection_raw = (
            self._optional_string(section, "connection") or "remora-spi"
        )
        if connection_raw not in ALLOWED_CONNECTION_TYPES:
            raise InvalidConnectionError(
                section_name, connection_raw, ALLOWED_CONNECTION_TYPES
            )
        board = self._optional_string(section, "board") or "BIGTREETECH OCTOPUS"
        return MCU(
            connection=connection_raw,
            interface=self._optional_string(section, "interface"),
            board=board,
        )

    @staticmethod
    def _validate_pin_mcu(
        section_name: str,
        key: str,
        pin: str | None,
        declared_mcus: list[str],
    ) -> None:
        """Reject a pin reference whose MCU prefix doesn't match a declared MCU.

        Bare pins (no ``:`` in their value) are accepted as implicit
        references to "the active remora MCU" — the compiler resolves
        them at emit time. Pins with a qualifier must match a section
        declared in the same profile; orphans raise
        :class:`UndefinedMcuError` with the source section, the
        schema key, and the list of valid MCU names so the operator
        can fix the typo in one glance.
        """
        mcu_name, _ = split_pin(pin)
        if mcu_name is None:
            return
        if mcu_name not in declared_mcus:
            raise UndefinedMcuError(
                section_name, key, mcu_name, declared_mcus
            )

    @staticmethod
    def _validate_all_pin_mcu_references(graph: MachineConfigGraph) -> None:
        """Walk every pin-emitting section once to enforce MCU qualifiers.

        The check runs after the graph is fully built so the
        :attr:`MachineConfigGraph.mcus` dict is complete and the
        declared-MCU list is final. Errors point at the offending
        section + key, never at an unnamed record.
        """
        declared = list(graph.mcus.keys())
        for section_name, stepper in graph.steppers.items():
            for attr in ("step_pin", "dir_pin", "enable_pin", "endstop_pin"):
                pin = getattr(stepper, attr, None)
                MachineConfigParser._validate_pin_mcu(
                    section_name, attr, pin, declared
                )
        for name, endstop in graph.endstop_switches.items():
            MachineConfigParser._validate_pin_mcu(
                f"endstop_switch {name}", "pin", endstop.pin, declared
            )
        for section_name, heater in graph.heaters.items():
            is_extruder = isinstance(heater, Extruder)
            pin_keys = [
                "heater_pin",
                "sensor_pin",
            ]
            if is_extruder:
                pin_keys.extend(["step_pin", "dir_pin", "enable_pin"])
            for attr in pin_keys:
                pin = getattr(heater, attr, None)
                MachineConfigParser._validate_pin_mcu(
                    section_name, attr, pin, declared
                )
        if graph.spindle_analog is not None:
            for attr in ("pwm_pin", "enable_pin"):
                MachineConfigParser._validate_pin_mcu(
                    "spindle_analog",
                    attr,
                    getattr(graph.spindle_analog, attr, None),
                    declared,
                )
        for section_name, tmc in graph.tmc2209s.items():
            MachineConfigParser._validate_pin_mcu(
                f"tmc2209 {section_name}",
                "uart_pin",
                tmc.uart_pin,
                declared,
            )
        for section_name, fan in graph.fans.items():
            MachineConfigParser._validate_pin_mcu(
                section_name, "pin", fan.pin, declared
            )

    def _parse_fan(
        self,
        section_name: str,
        section: configparser.SectionProxy,
    ) -> Fan:
        """Build a :class:`Fan` from a ``[fan]`` / ``[fan_generic foo]`` section.

        The canonical id is derived from the section header via
        :func:`derive_fan_name`. ``pin`` is required — the Remora
        board JSON needs a physical pin assignment for the PWM module.
        ``max_power`` is optional; the runtime scales it to 8-bit for
        the Remora ``PWM Max`` field when present.
        """
        for key in FAN_IGNORED_KEYS:
            if key in section:
                logger.info(
                    "Ignoring [%s] %s: it has no Remora equivalent",
                    section_name,
                    key,
                )
        pin = self._required_string(section_name, section, "pin")
        max_power = self._optional_float(section_name, section, "max_power")
        return Fan(
            name=derive_fan_name(section_name),
            pin=pin,
            max_power=max_power,
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


def _option_present(section: configparser.SectionProxy, key: str) -> bool:
    """True when ``key`` is in ``section`` and has a non-empty value."""
    if key not in section:
        return False
    return section[key].strip() != ""


def _find_section_name_for_mcu(
    name: str,
    mcus: dict,
) -> str | None:
    """Best-effort recovery of the source section header for an MCU.

    The parser only stores :class:`MCU` records — not the section
    headers they came from — because historically there was at most
    one such section. With multi-MCU support the duplicate-section
    diagnostic would prefer the original ``[mcu]`` / ``[mcu NAME]``
    header for human consumption.

    Returns ``None`` when the lookup fails — the parser then falls
    back to ``section_name`` from the call site, which is always
    available and is sufficient for the toast message.
    """
    # The dataclass doesn't currently carry the source header, so we
    # only know whether the key exists. Without a richer record the
    # caller falls back to ``section_name``; this stays as a hook
    # for the future introspection layer to fill in.
    _ = name, mcus
    return None


def _option_stripped(section: configparser.SectionProxy, key: str) -> str | None:
    if key not in section:
        return None
    value = section[key].strip()
    return value or None


# Descriptive alias for clients that refer to the input dialect explicitly.
KlipperConfigParser = MachineConfigParser


def parse_config(source_path: str | Path) -> MachineConfigGraph:
    """Parse ``source_path`` using :class:`MachineConfigParser`."""

    return MachineConfigParser(source_path).parse()


__all__ = [
    "ConfigValidationError",
    "DuplicateFanError",
    "DuplicateHeaterError",
    "DuplicateMcuSectionError",
    "DuplicateSpindleError",
    "DuplicateStepperPinError",
    "InvalidConnectionError",
    "InvalidValueError",
    "KlipperConfigParser",
    "MachineConfigParser",
    "MissingRequiredKeywordError",
    "MultipleExtrudersError",
    "UndefinedKeywordError",
    "UndefinedMcuError",
    "UnknownStepperError",
    "UnsupportedSectionError",
    "derive_fan_name",
    "derive_heater_name",
    "derive_spindle_name",
    "parse_config",
    "split_pin",
]
