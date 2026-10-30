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
from models.machineconfig.DiagnosticModels import Diagnostic, Severity
from models.machineconfig.PinModels import CapabilityClass, ParsedPin

from .mcus.RemoraCanMapper import RemoraCanMapper

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


#: Pins a CAN node can carry (Remora-m8p CAN expansion: Digital Pin and
#: Stepgen) — besides every ``endstops[].pin`` and every joint pin.
_CAN_NODE_PIN_FIELDS = frozenset({("estop", "fault_pin"), ("estop", "out_pin")})
MAX_CAN_NODES = 15
#: Step generators one node runs (firmware limit).
MAX_CAN_NODE_JOINTS = 2
#: TMC2209 drivers one node configures over its UART (firmware limit).
MAX_CAN_NODE_DRIVERS = 2


class MachineValidator:
    """Collects diagnostics for one ``hardware.json`` payload."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self._found: list[Diagnostic] = []
        # ``[duplicate_pin_override]``'s allowlist — an operator has
        # explicitly said sharing this physical pin is intentional, so
        # `_check_pin_conflict` must not flag it. Only this one check
        # honours it; every other rule still runs normally.
        self._duplicate_pin_overrides = frozenset(
            str(p) for p in (payload.get("duplicate_pin_overrides") or [])
        )

    # -- public surface ------------------------------------------------ #

    def validate(self) -> list[Diagnostic]:
        """Run every rule. Errors first, then warnings, else declaration order."""
        self._found = []
        # Parsed once: a malformed pin is reported once, not per rule.
        self._pins = self._parsed_pins()
        self._check_mcus()
        self._check_pins()
        self._check_can()
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
        """Each MCU's class — a CAN node's is its hub's: its joints reach
        LinuxCNC as ``remora.joint.N`` through the hub."""
        mcus_by_id = {str(m["id"]): m for m in self._records("mcus") if m.get("id")}
        classes: dict[str, CapabilityClass | None] = {}
        for mcu_id, mcu in mcus_by_id.items():
            if RemoraCanMapper.is_node(mcu):
                mcu = mcus_by_id.get(RemoraCanMapper.hub_id(mcu, mcus_by_id) or "", mcu)
            classes[mcu_id] = CapabilityClass.for_connection(mcu.get("connection"))
        return classes

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

        # ``estop`` is a top-level singleton object, not a list — it
        # can't ride ``_PIN_FIELDS``' generic ``_records()`` walk, so
        # it gets its own two-field pass folded into the same output
        # every other check (unknown-MCU, pin-conflict) already walks.
        estop = self._payload.get("estop")
        if isinstance(estop, dict):
            for field in ("fault_pin", "out_pin"):
                raw = estop.get(field)
                if not raw:
                    continue
                try:
                    out.append((PinStringMapper.from_string(raw), "estop", field, False))
                except ValueError as exc:
                    self._error("E_MALFORMED_PIN", str(exc), "estop")

        # ``probe`` / ``tool_length_sensor`` are the same shape of
        # singleton object as ``estop``, just one field — folded in for
        # the same reason.
        for component in ("probe", "tool_length_sensor"):
            record = self._payload.get(component)
            if not isinstance(record, dict):
                continue
            raw = record.get("pin")
            if raw:
                try:
                    out.append((PinStringMapper.from_string(raw), component, "pin", False))
                except ValueError as exc:
                    self._error("E_MALFORMED_PIN", str(exc), component)
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

        for pin, owner, field, drives_joint in self._pins:
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
        if pin.qualified in self._duplicate_pin_overrides:
            # The operator has explicitly said sharing this physical
            # pin is intentional — never record it, so it can never
            # conflict with itself or anything else either.
            return

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

    def _check_can(self) -> None:
        """CAN nodes (``remora-can``) behind a Remora hub.

        A node needs a hub it can name or find (``E_CAN_NO_HUB``), a
        unique UUID (``E_CAN_DUPLICATE_UUID``) and a free number 1 ... 15
        (``E_CAN_NODE_NUMBER``). It carries digital pins — endstops and
        the E-stop pins — and up to two joints, each with all its pins on
        that node (``E_CAN_NODE_JOINT``), and up to two TMC2209 UART
        drivers; anything else is
        ``E_CAN_NODE_PIN``: heaters, fans and sensors follow in later
        firmware phases, and
        the few-millisecond latency rules out a touch probe.
        """
        mcus_by_id = {str(m["id"]): m for m in self._records("mcus") if m.get("id")}
        nodes = [m for m in mcus_by_id.values() if RemoraCanMapper.is_node(m)]
        if not nodes:
            return

        uuids: dict[str, str] = {}
        by_hub: dict[str, list[dict[str, Any]]] = {}
        for node in nodes:
            node_id = str(node["id"])
            hub_id = RemoraCanMapper.hub_id(node, mcus_by_id)
            if hub_id is None:
                self._error(
                    "E_CAN_NO_HUB",
                    f"CAN node {node_id!r} has no hub: set can_hub to a remora-spi MCU"
                    + (f" ({node['can_hub']!r} is none)" if node.get("can_hub") else
                       " (needed when the machine has not exactly one remora-spi MCU)."),
                    node_id,
                )
            else:
                by_hub.setdefault(hub_id, []).append(node)
            uuid = str(node.get("canbus_uuid") or "")
            if uuid in uuids:
                self._error(
                    "E_CAN_DUPLICATE_UUID",
                    f"canbus_uuid {uuid} is used by both {uuids[uuid]!r} and {node_id!r}.",
                    node_id,
                )
            uuids.setdefault(uuid, node_id)

        for hub_id, hub_nodes in by_hub.items():
            declared = [int(n["can_node"]) for n in hub_nodes if n.get("can_node")]
            if len(hub_nodes) > MAX_CAN_NODES or len(declared) != len(set(declared)):
                self._error(
                    "E_CAN_NODE_NUMBER",
                    f"hub {hub_id!r}: node numbers must be unique, 1 ... {MAX_CAN_NODES} "
                    f"({len(hub_nodes)} node(s), declared numbers {sorted(declared)}).",
                    hub_id,
                )

        node_ids = {str(n["id"]) for n in nodes}
        endstops = self._ids("endstops")
        for pin, owner, field, drives_joint in self._pins:
            allowed = (
                drives_joint
                or (owner, field) in _CAN_NODE_PIN_FIELDS
                or (field == "pin" and owner in endstops)
            )
            if pin.mcu_id in node_ids and not allowed:
                self._error(
                    "E_CAN_NODE_PIN",
                    f"{owner}.{field} {pin.raw!r} is on CAN node {pin.mcu_id!r}, which only "
                    "carries joints, endstops and the E-stop fault_pin / out_pin so far.",
                    owner,
                )
        self._check_can_joints(node_ids)
        self._check_can_drivers(node_ids)

    def _check_can_joints(self, node_ids: set[str]) -> None:
        """A node joint has every pin on that node, and a node runs at
        most :data:`MAX_CAN_NODE_JOINTS` of them."""
        joints_per_node: dict[str, list[str]] = {}
        for joint in self._records("joints"):
            owner = str(joint.get("id", "?"))
            mcus: set[str] = set()
            for field in ("step_pin", "dir_pin", "enable_pin"):
                if not joint.get(field):
                    continue
                try:
                    mcus.add(PinStringMapper.from_string(joint[field]).mcu_id)
                except ValueError:
                    continue  # E_MALFORMED_PIN, reported once already
            on_nodes = mcus & node_ids
            if not on_nodes:
                continue
            if len(mcus) > 1:
                self._error(
                    "E_CAN_NODE_JOINT",
                    f"joint {owner!r} has pins on {', '.join(sorted(mcus))}: a joint on a "
                    "CAN node needs its step, dir and enable pins all on that node.",
                    owner,
                )
                continue
            joints_per_node.setdefault(next(iter(on_nodes)), []).append(owner)
        for node_id, joints in joints_per_node.items():
            if len(joints) > MAX_CAN_NODE_JOINTS:
                self._error(
                    "E_CAN_NODE_JOINT",
                    f"CAN node {node_id!r} carries {len(joints)} joints ({', '.join(joints)}); "
                    f"a node runs at most {MAX_CAN_NODE_JOINTS}.",
                    node_id,
                )

    def _check_can_drivers(self, node_ids: set[str]) -> None:
        """A node configures at most :data:`MAX_CAN_NODE_DRIVERS` TMC2209
        drivers over its UART (firmware limit)."""
        drivers_per_node: dict[str, list[str]] = {}
        for driver in self._records("drivers"):
            raw = driver.get("uart_pin")
            if not raw:
                continue
            try:
                pin = PinStringMapper.from_string(raw)
            except ValueError:
                continue
            if pin.mcu_id in node_ids:
                drivers_per_node.setdefault(pin.mcu_id, []).append(str(driver.get("id", "?")))
        for node_id, drivers in drivers_per_node.items():
            if len(drivers) > MAX_CAN_NODE_DRIVERS:
                self._error(
                    "E_CAN_NODE_PIN",
                    f"CAN node {node_id!r} has {len(drivers)} TMC2209 UART drivers "
                    f"({', '.join(drivers)}); a node configures at most {MAX_CAN_NODE_DRIVERS}.",
                    node_id,
                )

    def _check_references(self) -> None:
        sensors = self._ids("temperature_sensors")
        fans = self._ids("fans")
        drivers = self._ids("drivers")
        endstops = self._ids("endstops")
        tools = self._ids("tools")

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

        for fan in self._records("fans"):
            if fan.get("kind") != "heater":
                continue
            owner = str(fan.get("id", "?"))
            heater = fan.get("heater")
            if heater and str(heater) not in tools:
                self._error(
                    "E_UNKNOWN_HEATER",
                    f"heater {heater!r} is not declared in tools[].",
                    owner,
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
