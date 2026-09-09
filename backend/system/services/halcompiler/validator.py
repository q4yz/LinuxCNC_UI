"""Can this machine be compiled, and if not, why not?

Runs the rules from ``.agent/component/README.md`` § 3 (plus the
per-component ones) over a ``hardware.json`` payload and returns every
finding at once. Nothing is raised: a config with six problems reports
six, so the operator fixes them in one pass.

Reads a plain ``dict`` rather than the Pydantic model on purpose — a
hand-edited ``hardware.json`` is exactly the case worth checking, and
it may not survive strict model validation.

No emission happens here. This is the gate the compiler runs before it
writes anything.
"""

from __future__ import annotations

from typing import Any, Iterable

from mappers.machineconfig import PinStringMapper
from models.machineconfig.diagnostic_models import Diagnostic, Severity
from models.machineconfig.pin_models import CapabilityClass, ParsedPin

#: ``(list name, field)`` pairs that hold a pin string, and whether the
#: pin drives a joint (which is what the capability rules care about).
_PIN_FIELDS: tuple[tuple[str, str, bool], ...] = (
    ("joints", "step_pin", True),
    ("joints", "dir_pin", True),
    ("joints", "enable_pin", True),
    ("endstops", "pin", False),
    ("tools", "heater_pin", False),
    ("tools", "pwm_pin", False),
    ("tools", "enable_pin", False),
    ("tools", "run_pin", False),
    ("tools", "reverse_pin", False),
    ("tools", "speed_pin", False),
    ("tools", "speed_fb_pin", False),
    ("tools", "at_speed_pin", False),
    ("tools", "fault_pin", False),
    ("tools", "is_connected_pin", False),
    ("tools", "error_count_pin", False),
    ("temperature_sensors", "pin", False),
    ("fans", "pin", False),
)


class MachineValidator:
    """Collects diagnostics for one ``hardware.json`` payload."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self._found: list[Diagnostic] = []

    # -- public surface ------------------------------------------------ #

    def validate(self) -> list[Diagnostic]:
        """Run every rule. Errors first, then warnings, else declaration order."""
        self._found = []
        self._check_mcus()
        self._check_pins()
        self._check_references()
        self._check_joints_and_axes()
        self._check_ranges()
        self._check_heaters()
        self._check_spindles()
        return sorted(self._found, key=lambda d: 0 if d.is_error else 1)

    @staticmethod
    def has_errors(diagnostics: Iterable[Diagnostic]) -> bool:
        return any(d.is_error for d in diagnostics)

    # -- helpers ------------------------------------------------------- #

    def _records(self, key: str) -> list[dict[str, Any]]:
        value = self._payload.get(key) or []
        return [r for r in value if isinstance(r, dict)]

    def _ids(self, key: str) -> set[str]:
        return {str(r["id"]) for r in self._records(key) if r.get("id")}

    def _error(self, code: str, message: str, where: str | None = None) -> None:
        self._found.append(Diagnostic(code, Severity.ERROR, message, where))

    def _warn(self, code: str, message: str, where: str | None = None) -> None:
        self._found.append(Diagnostic(code, Severity.WARNING, message, where))

    def _mcu_classes(self) -> dict[str, CapabilityClass | None]:
        return {
            str(m["id"]): CapabilityClass.for_connection(m.get("connection"))
            for m in self._records("mcus")
            if m.get("id")
        }

    def _parsed_pins(self) -> list[tuple[ParsedPin, str, str, bool]]:
        """Every parseable pin as ``(pin, owner_id, field, drives_joint)``."""
        out: list[tuple[ParsedPin, str, str, bool]] = []
        for list_name, field, is_joint in _PIN_FIELDS:
            for record in self._records(list_name):
                raw = record.get(field)
                if not raw:
                    continue
                owner = str(record.get("id", list_name))
                try:
                    out.append((PinStringMapper.from_string(raw), owner, field, is_joint))
                except ValueError as exc:
                    self._error("E_MALFORMED_PIN", str(exc), owner)
        return out

    # -- rules --------------------------------------------------------- #

    def _check_mcus(self) -> None:
        mcus = self._records("mcus")
        if not mcus:
            self._error("E_NO_MCU", "The machine declares no MCU.")
            return
        for mcu in mcus:
            if CapabilityClass.for_connection(mcu.get("connection")) is None:
                self._error(
                    "E_UNKNOWN_MCU_CLASS",
                    f"connection {mcu.get('connection')!r} maps to no capability "
                    "class, so the compiler cannot tell how motion reaches the motor.",
                    str(mcu.get("id", "?")),
                )

    def _check_pins(self) -> None:
        classes = self._mcu_classes()
        claimed: dict[str, tuple[str, str]] = {}
        motion_classes: set[CapabilityClass] = set()

        for pin, owner, field, drives_joint in self._parsed_pins():
            if pin.mcu_id not in classes:
                code = "E_NO_DEFAULT_MCU" if pin.mcu_id == "mcu" else "E_UNKNOWN_MCU"
                self._error(
                    code,
                    f"{field} {pin.raw!r} targets MCU {pin.mcu_id!r}, which is not declared.",
                    owner,
                )
                continue

            self._check_pin_conflict(pin, owner, field, claimed)

            mcu_class = classes[pin.mcu_id]
            if drives_joint and mcu_class is not None:
                motion_classes.add(mcu_class)
                if mcu_class is CapabilityClass.IO_ONLY:
                    self._error(
                        "E_MOTION_ON_IO_MCU",
                        f"{field} {pin.raw!r} puts motion on {pin.mcu_id!r}, which "
                        "cannot carry step/dir. Use a motion-capable MCU.",
                        owner,
                    )

        if len(motion_classes) > 1:
            names = ", ".join(sorted(c.name for c in motion_classes))
            self._error(
                "E_MIXED_MOTION_CLASS",
                f"joints span more than one motion class ({names}); one machine "
                "must use a single motion interface.",
            )

    def _check_pin_conflict(
        self,
        pin: ParsedPin,
        owner: str,
        field: str,
        claimed: dict[str, tuple[str, str]],
    ) -> None:
        previous = claimed.get(pin.qualified)
        if previous is None:
            claimed[pin.qualified] = (owner, field)
            return

        prev_owner, prev_field = previous
        # Known, generated case: `_fan_payload` derives a heater's fan
        # pin from that heater's own `heater_pin`, so every generated
        # machine has this pair. Real, but not the operator's typo —
        # report it without blocking the compile.
        heater_fan_pair = {prev_field, field} == {"heater_pin", "pin"} and (
            prev_owner.startswith("heater") or owner.startswith("fan")
        )
        if heater_fan_pair:
            self._warn(
                "W_FAN_SHARES_HEATER_PIN",
                f"{owner}.{field} and {prev_owner}.{prev_field} both drive "
                f"{pin.qualified} — one output cannot run a heater and its own "
                "cooling fan. Give the fan its own pin.",
                owner,
            )
            return

        self._error(
            "E_PIN_CONFLICT",
            f"{pin.qualified} is claimed by both {prev_owner}.{prev_field} "
            f"and {owner}.{field}.",
            owner,
        )

    def _check_references(self) -> None:
        sensors = self._ids("temperature_sensors")
        fans = self._ids("fans")
        drivers = self._ids("drivers")
        endstops = self._ids("endstops")

        for tool in self._records("tools"):
            owner = str(tool.get("id", "?"))
            if tool.get("sensor") and str(tool["sensor"]) not in sensors:
                self._error(
                    "E_UNKNOWN_SENSOR",
                    f"sensor {tool['sensor']!r} is not declared in temperature_sensors[].",
                    owner,
                )
            if tool.get("fan") and str(tool["fan"]) not in fans:
                self._error(
                    "E_UNKNOWN_FAN", f"fan {tool['fan']!r} is not declared.", owner
                )

        for joint in self._records("joints"):
            if joint.get("driver") and str(joint["driver"]) not in drivers:
                self._error(
                    "E_UNKNOWN_REF",
                    f"driver {joint['driver']!r} is not declared.",
                    str(joint.get("id", "?")),
                )

        for axis in self._records("axes"):
            if axis.get("endstop") and str(axis["endstop"]) not in endstops:
                self._error(
                    "E_UNKNOWN_REF",
                    f"endstop {axis['endstop']!r} is not declared.",
                    str(axis.get("id", "?")),
                )

    def _check_joints_and_axes(self) -> None:
        joints = self._records("joints")
        numbers = sorted(j["joint_number"] for j in joints if j.get("joint_number") is not None)
        if numbers and numbers != list(range(len(joints))):
            self._error(
                "E_JOINT_NUMBERING",
                f"joint_number values {numbers} are not contiguous 0..{len(joints) - 1}; "
                "LinuxCNC indexes [JOINT_N] sections densely.",
            )

        for axis in self._records("axes"):
            if not axis.get("joint_numbers"):
                self._error(
                    "E_AXIS_WITHOUT_JOINT",
                    "axis drives no joint, so nothing moves when it is commanded.",
                    str(axis.get("id", "?")),
                )

    def _check_ranges(self) -> None:
        for axis in self._records("axes"):
            owner = str(axis.get("id", "?"))
            low, high = axis.get("position_min"), axis.get("position_max")
            if low is not None and high is not None and low >= high:
                self._error(
                    "E_LIMITS", f"position_min ({low}) >= position_max ({high}).", owner
                )
            endstop = axis.get("position_endstop")
            if endstop is not None and low is not None and high is not None:
                if not (low <= endstop <= high):
                    self._error(
                        "E_LIMITS",
                        f"position_endstop ({endstop}) is outside [{low}, {high}]; "
                        "homing would drive the axis out of its own limits.",
                        owner,
                    )

        for tool in self._records("tools"):
            owner = str(tool.get("id", "?"))
            self._check_pair(tool, "min_rpm", "max_rpm", "E_RPM_RANGE", owner)
            self._check_pair(tool, "min_temp", "max_temp", "E_TEMP_RANGE", owner)

    def _check_pair(
        self, record: dict[str, Any], low_key: str, high_key: str, code: str, owner: str
    ) -> None:
        low, high = record.get(low_key), record.get(high_key)
        if low is not None and high is not None and low >= high:
            self._error(code, f"{low_key} ({low}) >= {high_key} ({high}).", owner)

    def _check_heaters(self) -> None:
        seen_sensors: dict[str, str] = {}
        for tool in self._records("tools"):
            if tool.get("type") not in ("extruder", "heated_bed", "heater"):
                continue
            owner = str(tool.get("id", "?"))

            # The app derives the heater's HAL pin suffix by stripping
            # "heater" from the id (HeaterMapper); an id that doesn't
            # start with it yields a malformed pin name.
            if not owner.startswith("heater"):
                self._error(
                    "E_HEATER_ID_PREFIX",
                    f"heater id {owner!r} must start with 'heater' — the HAL pin "
                    "suffix is derived by stripping that prefix.",
                    owner,
                )

            sensor = tool.get("sensor")
            if not sensor:
                continue
            if sensor in seen_sensors:
                self._error(
                    "E_SENSOR_SHARED",
                    f"sensor {sensor!r} is already read by {seen_sensors[sensor]!r}; "
                    "each control loop needs its own reading.",
                    owner,
                )
            else:
                seen_sensors[str(sensor)] = owner

    def _check_spindles(self) -> None:
        """`.agent/component/digital_spindle.md` § 4's business rules.

        Pin-level checks (unknown MCU, malformed pin, conflicting pin)
        already run generically over every field in :data:`_PIN_FIELDS`
        — this only covers what's specific to a digital spindle.
        """
        connections = {
            str(m["id"]): str(m.get("connection") or "")
            for m in self._records("mcus")
            if m.get("id")
        }
        seen_numbers: dict[Any, str] = {}

        for spindle in self._records("tools"):
            if spindle.get("type") != "spindle_digital":
                continue
            owner = str(spindle.get("id", "?"))

            if not spindle.get("run_pin"):
                self._error(
                    "E_SPINDLE_NO_RUN_PIN",
                    f"{owner} has no run_pin — nothing can start the spindle.",
                    owner,
                )

            min_rpm, max_rpm = spindle.get("min_rpm"), spindle.get("max_rpm")
            fixed_speed = min_rpm is not None and min_rpm == max_rpm
            if not spindle.get("speed_pin") and not fixed_speed:
                self._error(
                    "E_SPINDLE_NO_SPEED_PIN",
                    f"{owner} has no speed_pin, so the speed command has nowhere to go.",
                    owner,
                )

            if not (spindle.get("speed_fb_pin") or spindle.get("at_speed_pin")):
                self._warn(
                    "W_NO_SPINDLE_FEEDBACK",
                    f"{owner} has neither speed_fb_pin nor at_speed_pin — at-speed "
                    "is forced true, so G-code starts cutting before the spindle "
                    "has spun up. Add a dwell in the tool-change macro.",
                    owner,
                )

            connection = connections.get(self._spindle_mcu_id(spindle) or "", "")
            has_health = spindle.get("fault_pin") or spindle.get("is_connected_pin") or spindle.get("error_count_pin")
            if connection and connection != "dummy" and not has_health:
                self._warn(
                    "W_NO_SPINDLE_HEALTH",
                    f"{owner} declares none of fault_pin/is_connected_pin/"
                    f"error_count_pin on a {connection!r} link — a dropped "
                    "connection looks identical to a healthy, idle spindle in the UI.",
                    owner,
                )

            number = spindle.get("spindle_number")
            number = 0 if number is None else number
            if number in seen_numbers:
                self._error(
                    "E_MULTIPLE_SPINDLES",
                    f"{owner} and {seen_numbers[number]!r} both claim spindle_number "
                    f"{number}; give each spindle its own index and add it to "
                    "[TRAJ] SPINDLES.",
                    owner,
                )
            else:
                seen_numbers[number] = owner

    @staticmethod
    def _spindle_mcu_id(spindle: dict[str, Any]) -> str | None:
        """The MCU a spindle's pins target, read off whichever is declared first."""
        for field in ("run_pin", "speed_pin", "reverse_pin", "speed_fb_pin", "at_speed_pin"):
            raw = spindle.get(field)
            if not raw:
                continue
            try:
                return PinStringMapper.from_string(raw).mcu_id
            except ValueError:
                return None
        return None


def validate_machine(payload: dict[str, Any]) -> list[Diagnostic]:
    """Convenience wrapper — one call, every finding."""
    return MachineValidator(payload).validate()
