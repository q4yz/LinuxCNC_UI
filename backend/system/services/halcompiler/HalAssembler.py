"""Joins every component/MCU mapper's :class:`HalFragment` into one.

The only place global concerns live — the two-pass component/router
join, endstop signal de-duplication, and the fragment order that
implements `.agent/component/README.md` § 4. Everything else (what one
component or router actually emits) stays in its own small mapper
class; this coordinates, it doesn't decide content.

**Trusts its input.** Run :func:`services.halcompiler.validate_machine`
first — this assembler does not re-check referential integrity or
motion-class consistency, it assumes a payload with zero errors.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

from mappers.machineconfig import PinStringMapper
from models.machineconfig.HalFragmentModels import HalFragment, PinRequest, RouterMcu, combine
from models.machineconfig.HardwareJsonModels import McuInfo
from models.machineconfig.PinModels import CapabilityClass

from domain_file_services.paths import ACTIVE_BED_MESH_FILE

from models.machineconfig.HardwareRecords import HardwareRecords
from .components.BedMeshHalMapper import BedMeshHalMapper
from .components.CoreXyHalMapper import CoreXyHalMapper
from .components.DigitalSpindleHalMapper import DigitalSpindleHalMapper
from .components.EstopHalMapper import EstopHalMapper
from .components.ExtruderGuardHalMapper import ExtruderGuardHalMapper
from .components.JointShapeHalMapper import JointShapeHalMapper
from .components.InputPinHalMapper import InputPinHalMapper
from .components.OutputPinHalMapper import OutputPinHalMapper
from .components.FanHalMapper import FanHalMapper
from .components.HeaterHalMapper import HeaterHalMapper
from .components.MotionSystemHalMapper import MotionSystemHalMapper
from .components.ProbeHalMapper import ProbeHalMapper
from .components.RemoraDriverFirmwareMapper import RemoraDriverFirmwareMapper
from .components.RemoraFirmwareConfigMapper import RemoraFirmwareConfigMapper
from .components.RemoraStepperHalMapper import RemoraStepperHalMapper
from .components.Adxl345HalMapper import Adxl345HalMapper
from .components.LedHalMapper import LedHalMapper
from .components.StepperHalMapper import StepperHalMapper
from .components.ZTiltHalMapper import ZTiltHalMapper
from .components.TemperatureSensorHalMapper import TemperatureSensorHalMapper
from .mcus.ParportRouterMapper import ParportRouterMapper
from .mcus.RemoraCanMapper import RemoraCanMapper
from .mcus.RemoraRouterMapper import RemoraRouterMapper
from .mcus.VfdRs485RouterMapper import VfdRs485RouterMapper

#: MCU ``connection`` value -> the router mapper that handles it.
#: A request that resolves to any other MCU raises
#: :class:`UnsupportedMcuError` rather than being silently dropped.
#: ``remora-eth`` is deliberately absent — no reference machine exists
#: for it yet, so it stays honestly unimplemented. ``rs485`` is the
#: pre-rename alias for ``vfd_rs485`` (``CapabilityClass.for_connection``
#: already treats them the same way).
_ROUTERS: dict[str, Any] = {
    "parallelport": ParportRouterMapper,
    "remora-spi": RemoraRouterMapper,
    "vfd_rs485": VfdRs485RouterMapper,
    "rs485": VfdRs485RouterMapper,
}

#: Per-axis mapper for each motion capability class. IO_ONLY never
#: reaches here — a joint on a class-C MCU is ``E_MOTION_ON_IO_MCU``,
#: caught by the validator the assembler trusts to have already run.
_STEPPER_MAPPERS: dict[CapabilityClass, Any] = {
    CapabilityClass.STEP_DIR: StepperHalMapper,
    CapabilityClass.POSITION: RemoraStepperHalMapper,
}

class UnsupportedMcuError(NotImplementedError):
    """A pin needs an MCU connection type this compiler doesn't route yet."""


class HalAssembler:
    """Compiles one machine's ``hardware.json`` payload into a :class:`HalFragment`."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self._axes = HardwareRecords.axes(payload)
        self._joints_by_number = {j.joint_number: j for j in HardwareRecords.joints(payload)}
        self._endstops_by_id = {e.id: e for e in HardwareRecords.endstops(payload)}
        self._mcus_by_id = {m.id: m for m in HardwareRecords.mcus(payload)}
        # X / Y joints behind the jointshape component (input shaper, skew)
        self._shaped: dict[int, str] = {}
        # Typed records (HardwareRecords); the payload itself stays a dict.
        self._tools = HardwareRecords.tools(payload)
        self._joints = list(self._joints_by_number.values())
        self._sensors_by_id = {s.id: s for s in HardwareRecords.temperature_sensors(payload)}
        self._fans = HardwareRecords.fans(payload)
        self._fans_by_id = {f.id: f for f in self._fans}
        self._output_pins = HardwareRecords.output_pins(payload)
        self._input_pins = HardwareRecords.input_pins(payload)
        self._output_pins_by_id = {p.id: p for p in self._output_pins}
        self._tools_by_id = {t.id: t for t in self._tools}
        self._drivers_by_id = {d.id: d for d in HardwareRecords.drivers(payload)}
        # ``[duplicate_pin_override]``'s allowlist — see
        # ``_merge_override_duplicates``. The validator trusts this
        # list to skip ``E_PIN_CONFLICT``; the assembler is what makes
        # the resulting HAL actually valid.
        self._duplicate_pin_overrides = frozenset(
            str(p) for p in (payload.get("duplicate_pin_overrides") or [])
        )

    def assemble(self) -> HalFragment:
        capability_class = self._capability_class()
        component_fragments = (
            self._component_fragments(capability_class)
            + self._spindle_fragments()
            + self._heater_fragments()
            + self._sensor_fragments()
            + [LedHalMapper.to_fragment(led) for led in HardwareRecords.leds(self._payload)]
            + [Adxl345HalMapper.to_fragment(HardwareRecords.adxl345(self._payload))]
            + self._fan_fragments()
            + self._driver_fragments(capability_class)
            + [self._estop_fragment(), self._probe_fragment()]
            + self._bed_mesh_fragments()
            + self._io_pin_fragments()
        )
        z_tilt = HardwareRecords.z_tilt(self._payload)
        if z_tilt is not None:
            # After every stepper mapper: it rewrites their Z position nets.
            component_fragments.append(ZTiltHalMapper.to_fragment(z_tilt, component_fragments))
        self._merge_override_duplicates(component_fragments)
        motion = MotionSystemHalMapper.to_fragment(len(self._joints_by_number), capability_class)

        requests = self._deduplicated_requests(component_fragments)
        router_bases, router_routes = self._route(requests)

        # Order per README § 4: loadrt (motion, then MCU drivers) -> addf
        # -> setp -> component-local nets -> router nets. combine()
        # concatenates each field in fragment order, so this list order
        # is what actually produces that field-level ordering.
        result = combine([motion, *router_bases, *component_fragments, *router_routes])
        self._render_firmware_configs(result)
        return result

    # -- capability class --------------------------------------------------- #

    def _capability_class(self) -> CapabilityClass:
        """The motion MCU's class, read off a joint's own ``step_pin``.

        Resolved *before* building any component fragment — the class
        decides which stepper mapper to dispatch to, since class B
        emits no STEP/DIR :class:`PinRequest` at all (Remora owns the
        pulses, so there is nothing to route). Not "the first declared
        MCU": a machine can carry an unrelated class-C MCU (a VFD
        spindle) alongside its motion controller, and declaration order
        says nothing about which one carries joints. A CAN node's joint
        is its hub's (``remora.joint.N`` through the hub).
        """
        for joint in self._joints:
            if not joint.step_pin:
                continue
            mcu_id = self._routing_mcu_id(PinStringMapper.from_string(joint.step_pin).mcu_id)
            mcu = self._mcus_by_id.get(mcu_id)
            if mcu is None:
                continue
            resolved = CapabilityClass.for_connection(mcu.connection)
            if resolved is not None:
                return resolved
        return CapabilityClass.STEP_DIR

    def _motion_mcu_ids(self) -> set[str]:
        """Every MCU that owns at least one joint's ``step_pin`` — a CAN
        node's hub for a node joint.

        Used by ``_route`` to force that MCU's ``base_fragment()`` to
        run even with zero routed :class:`PinRequest`\\ s — see the
        call site for why that matters on class B.
        """
        ids: set[str] = set()
        for joint in self._joints:
            if joint.step_pin:
                ids.add(self._routing_mcu_id(PinStringMapper.from_string(joint.step_pin).mcu_id))
        return ids

    # -- pass 1: components ---------------------------------------------- #

    def _corexy_joints(self) -> tuple[int, int] | None:
        """The X / Y joint numbers of a ``kinematics: corexy`` machine
        (validated: one joint each, `MachineValidator._check_corexy`)."""
        if self._payload.get("kinematics") != "corexy":
            return None
        by_id = {a.id: a.joint_numbers for a in self._axes}
        return by_id["x"][0], by_id["y"][0]

    def _xy_joints(self) -> tuple[int, int] | None:
        """The first X and Y joint (Cartesian joints, before any CoreXY
        mixing): their ``vel-cmd`` is the head's X / Y speed."""
        first = {a.id.lower(): a.joint_numbers[0] for a in self._axes if a.joint_numbers}
        return (first["x"], first["y"]) if "x" in first and "y" in first else None

    def _flow_joints(self, capability_class: CapabilityClass) -> frozenset[int]:
        """Extruder joints whose position goes through the Remora
        ``extruder`` component (flow %) — Remora boards only."""
        if _STEPPER_MAPPERS.get(capability_class, StepperHalMapper) is not RemoraStepperHalMapper:
            return frozenset()
        joints = (ExtruderGuardHalMapper.guarded_joint(t, self._joints) for t in self._tools)
        return frozenset(j for j in joints if j is not None)

    def _component_fragments(self, capability_class: CapabilityClass) -> list[HalFragment]:
        mapper = _STEPPER_MAPPERS.get(capability_class, StepperHalMapper)
        self._shaped = JointShapeHalMapper.shaped_joints(self._payload)
        corexy = self._corexy_joints()
        fragments: list[HalFragment] = []
        for axis in self._axes:
            joints = [self._joints_by_number[n] for n in axis.joint_numbers if n in self._joints_by_number]
            if not joints:
                continue
            # The full endstops-by-id map, not one axis-level lookup —
            # a dual-motor (gantry) axis's joints can each reference a
            # DIFFERENT switch (see hardware_json_generator.py's
            # per-joint ``endstop`` field); the mapper resolves each
            # joint's own reference itself instead of the whole axis
            # sharing one.
            routed = frozenset(corexy or ()) | self._flow_joints(capability_class) | frozenset(self._shaped)
            if routed and mapper is RemoraStepperHalMapper:
                fragments.append(mapper.to_fragment(axis, joints, self._endstops_by_id, routed))
            else:
                fragments.append(mapper.to_fragment(axis, joints, self._endstops_by_id))
        # On CoreXY the shapers act on X / Y before the mixing (both mappers
        # agree on the j<n>pos-cmd-shaped / j<n>pos-fb signals between them).
        # The shapers first: in the same servo tier (2) as the CoreXY motor
        # sums, emission order decides, and the sums need the shaped X / Y.
        shaped_corexy = bool(corexy) and set(corexy) <= set(self._shaped)
        if self._shaped:
            fragments.append(JointShapeHalMapper.to_fragment(
                HardwareRecords.input_shaper(self._payload), self._shaped, corexy=shaped_corexy))
        if corexy:
            fragments.append(CoreXyHalMapper.to_fragment(*corexy, shaped=shaped_corexy))
        return fragments

    def _spindle_fragments(self) -> list[HalFragment]:
        """One fragment per digital spindle — independent of motion class.

        A spindle carries its own MCU (a VFD, an EtherCAT drive); it is
        never dispatched through a stepper mapper, and its presence or
        absence has no bearing on which stepper mapper the joints get.
        """
        return [
            DigitalSpindleHalMapper.to_fragment(tool) for tool in self._tools if tool.type == "spindle_digital"
        ]

    def _heater_fragments(self) -> list[HalFragment]:
        """One fragment per heater-shaped tool — thermal half only.

        Independent of motion class for the same reason a spindle is:
        a heater's pin is just a pin, resolved through whichever MCU
        its `heater_pin`/sensor pin happen to name. An extruder's own
        motion joint already got its fragment from
        ``_component_fragments`` — this only ever adds the PID/
        watermark loop and the sensor/fan wiring, never step/dir.
        """
        fragments: list[HalFragment] = []
        for tool in self._tools:
            if tool.type not in ("extruder", "heated_bed"):
                continue
            sensor = self._sensors_by_id.get(tool.sensor or "")
            fan = self._fans_by_id.get(tool.fan or "")
            fragments.append(HeaterHalMapper.to_fragment(tool, sensor, fan))
            # An extruder's cold-extrusion guard (min_extrude_temp).
            joint = ExtruderGuardHalMapper.guarded_joint(tool, self._joints)
            if joint is not None:
                flow = joint in self._flow_joints(self._capability_class())
                fragments.append(ExtruderGuardHalMapper.to_fragment(tool, joint, flow=flow, xy_joints=self._xy_joints()))
        return fragments

    def _sensor_fragments(self) -> list[HalFragment]:
        """One fragment per temperature sensor no heater reads — a heater's
        own sensor is already wired by ``HeaterHalMapper``."""
        return [TemperatureSensorHalMapper.to_fragment(s) for s in TemperatureSensorHalMapper.unclaimed_sensors(self._payload)]

    def _fan_fragments(self) -> list[HalFragment]:
        """One fragment per fan — always its own direct pin route.

        Independent of motion class, like a spindle or heater's own
        pin. A `kind: "part"` fan a heater also references (its own
        auto-derived placeholder, or a real one) ends up with the
        *same* signal name here and in `HeaterHalMapper`'s own fan
        handling — `_deduplicated_requests` collapses the two into one
        route, no `duplicate_pin_override` needed (same signal name,
        not two different ones sharing a pin).
        """
        return [
            FanHalMapper.to_fragment(fan, self._tools_by_id, self._sensors_by_id) for fan in self._fans
        ]

    def _estop_fragment(self) -> HalFragment:
        """Always present, independent of motion class — the UI pulse
        chain needs no hardware, and the optional physical chain
        decides its own MCU-class gating internally (see
        ``EstopHalMapper._owns_iocontrol_chain``)."""
        return EstopHalMapper.to_fragment(HardwareRecords.estop(self._payload), self._mcus_by_id)

    def _io_pin_fragments(self) -> list[HalFragment]:
        """``[output_pin]`` / ``[input_pin]``, any MCU that can route them."""
        sets = InputPinHalMapper.halpin_sets(self._input_pins)
        return [
            OutputPinHalMapper.to_fragment(p, [s for s in sets if s.output_id == p.id]) for p in self._output_pins
        ] + [InputPinHalMapper.to_fragment(p) for p in self._input_pins]

    def _with_output_pin_period(self, module: dict[str, object]) -> dict[str, object]:
        """An ``[output_pin]`` PWM module gets ``"Period us"`` from its
        ``cycle_time`` (seconds)."""
        output_pin = self._output_pins_by_id.get(str(module.get("Comment", "")))
        if module.get("Type") != "PWM" or output_pin is None:
            return module
        return {**module, "Period us": round(output_pin.cycle_time * 1_000_000)}

    def _bed_mesh_fragments(self) -> list[HalFragment]:
        """The bed mesh compensation, only with ``[bed_mesh]``."""
        if HardwareRecords.bed_mesh(self._payload) is None:
            return []
        return [BedMeshHalMapper.to_fragment(ACTIVE_BED_MESH_FILE.as_posix())]

    def _probe_fragment(self) -> HalFragment:
        """A no-op empty fragment when the machine declared no
        ``[probe]`` at all — unlike estop, that's the normal case, not
        something to fall back to a default object for."""
        # probe:z_virtual_endstop: the probe is also the home switch of
        # every Z joint (LinuxCNC's own homing, AxisBuilder._home_z_on_probe).
        z_home_joints: list[int] = []
        if HardwareRecords.z_virtual_endstop(self._payload) is not None:
            for axis in self._axes:
                if axis.id.lower() == "z":
                    z_home_joints = list(axis.joint_numbers)
        probe = HardwareRecords.probe(self._payload)
        return ProbeHalMapper.to_fragment(
            probe,
            HardwareRecords.tool_length_sensor(self._payload),
            z_home_joints=z_home_joints,
            latch_joint=self._probe_latch_joint(probe.pin if probe is not None else None),
        )

    def _probe_latch_joint(self, probe_pin: str | None) -> int | None:
        """Z's first joint when the probe pin and that joint's step generator
        are on the same Remora SPI board (the board latches the step count at
        the trigger edge); ``None`` otherwise — a probe on a CAN node or
        another board cannot see Z's step count."""
        if not probe_pin:
            return None
        z_axis = next((a for a in self._axes if a.id.lower() == "z"), None)
        if z_axis is None or not z_axis.joint_numbers:
            return None
        number = z_axis.joint_numbers[0]
        joint = self._joints_by_number.get(number)
        if joint is None or not joint.step_pin:
            return None
        try:
            probe_mcu = PinStringMapper.from_string(probe_pin).mcu_id
            z_mcu = PinStringMapper.from_string(joint.step_pin).mcu_id
        except ValueError:
            return None
        mcu = self._mcus_by_id.get(z_mcu)
        if probe_mcu != z_mcu or mcu is None or mcu.connection != "remora-spi":
            return None
        return number

    def _driver_fragments(self, capability_class: CapabilityClass) -> list[HalFragment]:
        """A `TMC2209` firmware module per joint whose driver has a UART pin.

        Firmware-only — `RemoraDriverFirmwareMapper` never emits a
        `net`. Gated on class B: `config.txt` doesn't exist for any
        other MCU type, so a class-A machine that happens to also
        declare a `[tmc2209 ...]` section must not produce a spurious
        `config_<mcu>.txt` for a board that will never read one.
        """
        if capability_class is not CapabilityClass.POSITION:
            return []
        fragment = RemoraDriverFirmwareMapper.to_fragment(self._joints, self._drivers_by_id)
        return [fragment] if fragment.firmware_modules else []

    def _merge_override_duplicates(self, fragments: list[HalFragment]) -> None:
        """Make an operator-permitted shared physical pin actually valid HAL.

        A HAL pin can be linked to exactly one signal — that's why the
        shared-endstop path (`StepperHalMapper`) has both axes compute
        the *same* signal name up front rather than relying on
        de-duplication after the fact. `[duplicate_pin_override]`
        covers the case that trick can't: two independently-built
        component fragments, each with its own signal name, that
        happen to share one physical pin the operator has explicitly
        allowed (`_check_pin_conflict` already skipped `E_PIN_CONFLICT`
        for it). Without this step the router would still try to bind
        two different signal names to one pin — invalid at HAL load
        even though the validator no longer complains.

        Fix: pick the first-seen signal name as canonical and rewrite
        every other fragment's `net` lines and `PinRequest`s that named
        a "losing" signal to use it instead, so they all collapse onto
        one physical route like a true shared endstop would.
        """
        if not self._duplicate_pin_overrides:
            return

        by_pin: dict[str, list[str]] = {}
        for fragment in fragments:
            for request in fragment.requests:
                if request.pin.qualified in self._duplicate_pin_overrides:
                    signals = by_pin.setdefault(request.pin.qualified, [])
                    if request.signal not in signals:
                        signals.append(request.signal)

        renames = {
            losing: signals[0]
            for signals in by_pin.values()
            if len(signals) > 1
            for losing in signals[1:]
        }
        if not renames:
            return

        for fragment in fragments:
            fragment.nets = [self._rename_signal(line, renames) for line in fragment.nets]
            fragment.requests = [
                dataclasses.replace(r, signal=renames[r.signal]) if r.signal in renames else r
                for r in fragment.requests
            ]

    @staticmethod
    def _rename_signal(net_line: str, renames: dict[str, str]) -> str:
        return " ".join(renames.get(token, token) for token in net_line.split())

    # -- firmware sidecars -------------------------------------------------- #

    def _render_firmware_configs(self, fragment: HalFragment) -> None:
        """Group every :class:`FirmwareModuleRequest` by MCU into ``config_<id>.txt``.

        Cross-fragment aggregation (a Remora machine's joints and its
        endstops contribute modules from different mappers) is exactly
        what the assembler exists to coordinate — no single mapper sees
        the whole board's module list.

        The root shape itself (``{"Board": ..., "Modules": [...]}``) is
        :class:`RemoraFirmwareConfigMapper`'s call, not this method's —
        this only decides *which* modules belong to *which* MCU.
        """
        by_mcu: dict[str, list[dict[str, object]]] = {}
        for request in fragment.firmware_modules:
            by_mcu.setdefault(request.mcu_id, []).append(self._with_output_pin_period(request.module))

        # CAN nodes have no SD card: their modules go into the hub's
        # config.txt ("CAN" -> "Nodes"), never a config_<node>.txt.
        node_modules = {
            mcu_id: [
                RemoraCanMapper.pwm_settings(module, self._tools_by_id, self._fans_by_id)
                for module in by_mcu.pop(mcu_id)
            ]
            for mcu_id in list(by_mcu)
            if self._is_node(mcu_id)
        }
        hubs = {
            hub_id for mcu in self._mcus_by_id.values()
            if RemoraCanMapper.is_node(mcu.connection) and (hub_id := RemoraCanMapper.hub_of(mcu, self._mcus_by_id))
        }
        for hub_id in hubs:
            by_mcu.setdefault(hub_id, [])

        for mcu_id, modules in by_mcu.items():
            mcu = self._mcus_by_id.get(mcu_id)
            config = RemoraFirmwareConfigMapper.to_config(mcu, modules)
            if mcu is not None and mcu_id in hubs:
                config["CAN"] = RemoraCanMapper.can_block(
                    mcu, RemoraCanMapper.nodes_of(mcu_id, self._mcus_by_id), node_modules
                )
            config_file = f"config_{mcu_id}.txt"
            fragment.files[config_file] = json.dumps(config, indent=2)
            # The file exists now, so the board can be synced from it at
            # every LinuxCNC start (relative: HAL runs in this folder).
            if mcu is not None and mcu.connection == "remora-spi":
                sync = RemoraRouterMapper.config_sync_line(mcu, config_file)
                if sync:
                    fragment.preload.append(sync)
                    script = RemoraRouterMapper.config_sync_script(mcu, config_file)
                    if script is not None:
                        fragment.files[RemoraRouterMapper.sync_script_name(config_file)] = script

    # -- pass 2: routing --------------------------------------------------- #

    @staticmethod
    def _deduplicated_requests(fragments: list[HalFragment]) -> list[PinRequest]:
        """Same signal requested twice (a shared endstop) routes once.

        First occurrence wins; both axes still keep their own reader
        `net` line into their own joint (that part isn't deduplicated,
        only the physical-pin route is).
        """
        by_signal: dict[str, PinRequest] = {}
        for fragment in fragments:
            for request in fragment.requests:
                by_signal.setdefault(request.signal, request)
        return list(by_signal.values())

    def _routing_mcu_id(self, mcu_id: str) -> str:
        """A CAN node's pins route through its hub (one shared bit-space,
        `RemoraCanMapper`); every other MCU routes its own."""
        mcu = self._mcus_by_id.get(mcu_id)
        if mcu is not None and RemoraCanMapper.is_node(mcu.connection):
            return RemoraCanMapper.hub_of(mcu, self._mcus_by_id) or mcu_id
        return mcu_id

    def _is_node(self, mcu_id: str) -> bool:
        mcu = self._mcus_by_id.get(mcu_id)
        return mcu is not None and RemoraCanMapper.is_node(mcu.connection)

    def _can_status_bit(self, mcu_id: str) -> int | None:
        mcu = self._mcus_by_id.get(mcu_id)
        if mcu is None or mcu.connection != "remora-spi":
            return None
        return RemoraCanMapper.status_bit(mcu, RemoraCanMapper.nodes_of(mcu_id, self._mcus_by_id))

    def _route(self, requests: list[PinRequest]) -> tuple[list[HalFragment], list[HalFragment]]:
        by_mcu: dict[str, list[PinRequest]] = {}
        for request in requests:
            by_mcu.setdefault(self._routing_mcu_id(request.pin.mcu_id), []).append(request)

        # A class B motion MCU (Remora) generates no step/dir/enable
        # PinRequest at all — the board owns the pulses, so a bare
        # motion-only machine (no endstops, no heaters, nothing else
        # routed) would otherwise never call `base_fragment()` and so
        # never `loadrt remora-spi` in the first place, even though
        # every joint's `remora.joint.N.*` pins depend on it existing.
        # The board's own load is not conditional on whether anything
        # else happens to route through it.
        for mcu_id in self._motion_mcu_ids():
            by_mcu.setdefault(mcu_id, [])

        bases: list[HalFragment] = []
        routes: list[HalFragment] = []
        for mcu_id, mcu_requests in by_mcu.items():
            mcu = self._mcus_by_id.get(mcu_id)
            if mcu is None:
                continue  # E_UNKNOWN_MCU is the validator's job, not this one's.
            router = _ROUTERS.get(mcu.connection)
            if router is None:
                raise UnsupportedMcuError(
                    f"no HAL router implemented yet for MCU {mcu_id!r} "
                    f"(connection={mcu.connection!r})"
                )
            bases.append(router.base_fragment(self._router_mcu(mcu, mcu_requests)))
            if router is RemoraRouterMapper:
                routes.append(router.route(mcu_requests, reserved_input=self._can_status_bit(mcu_id)))
            else:
                routes.append(router.route(mcu_requests))
        return bases, routes

    def _router_mcu(self, mcu: McuInfo, mcu_requests: list[PinRequest]) -> RouterMcu:
        """The MCU for its router's ``base_fragment``, with what the rest of
        the machine says about it.

        A bare MCU record has no notion of "which spindle rides this bus"
        — that lives on the tool — so ``VfdRs485RouterMapper`` (the only
        router that needs it, for ``vfd.ini``'s ``MaxSpeedRPM`` /
        ``MinSpeedRPM``) gets it here. Per the "one drive per MCU" rule
        (``mcu_vfd_rs485.md`` § 4), every request routed to a given VFD
        MCU belongs to the same spindle, so the first request's ``owner``
        names it.

        ``estop_fault``: the ``[estop]`` ``fault_pin`` is read through this
        MCU — a class-B router (Remora) owns ``iocontrol.0.emc-enable-in``
        for its link health and must gate it on that input itself
        (``EstopHalMapper`` skips the chain there). ``can_status_bit``: a
        CAN hub gates LinuxCNC's enable on its nodes' status bit.
        """
        spindle = self._tools_by_id.get(mcu_requests[0].owner) if mcu_requests else None
        return RouterMcu(
            mcu=mcu,
            can_status_bit=self._can_status_bit(mcu.id),
            estop_fault=any(request.signal == "estop-fault" for request in mcu_requests),
            spindle_min_rpm=spindle.min_rpm if spindle else None,
            spindle_max_rpm=spindle.max_rpm if spindle else None,
        )

def assemble_machine(payload: dict[str, Any]) -> HalFragment:
    """Convenience wrapper — one call, the fully joined fragment."""
    return HalAssembler(payload).assemble()


__all__ = ["HalAssembler", "UnsupportedMcuError", "assemble_machine"]
