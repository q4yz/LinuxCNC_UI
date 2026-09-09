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

import json
from typing import Any

from mappers.machineconfig import PinStringMapper
from models.machineconfig.hal_fragment_models import HalFragment, PinRequest, combine
from models.machineconfig.pin_models import CapabilityClass

from .components.DigitalSpindleHalMapper import DigitalSpindleHalMapper
from .components.MotionSystemHalMapper import MotionSystemHalMapper
from .components.RemoraStepperHalMapper import RemoraStepperHalMapper
from .components.StepperHalMapper import StepperHalMapper
from .mcus.ParportRouterMapper import ParportRouterMapper
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

#: Board-side thread frequencies written into a Remora `config.txt`.
#: Hardcoded documented defaults, same precedent as
#: :class:`.components.StepperHalMapper`'s stepgen timing constants —
#: not yet sourced from a config field.
_FIRMWARE_BASE_HZ = 40000
_FIRMWARE_SERVO_HZ = 1000


class UnsupportedMcuError(NotImplementedError):
    """A pin needs an MCU connection type this compiler doesn't route yet."""


class HalAssembler:
    """Compiles one machine's ``hardware.json`` payload into a :class:`HalFragment`."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self._joints_by_number = {
            j["joint_number"]: j for j in payload.get("joints", []) if "joint_number" in j
        }
        self._endstops_by_id = {e["id"]: e for e in payload.get("endstops", []) if e.get("id")}
        self._mcus_by_id = {m["id"]: m for m in payload.get("mcus", []) if m.get("id")}

    def assemble(self) -> HalFragment:
        capability_class = self._capability_class()
        component_fragments = self._component_fragments(capability_class) + self._spindle_fragments()
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
        says nothing about which one carries joints.
        """
        for joint in self._joints_by_number.values():
            step_pin = joint.get("step_pin")
            if not step_pin:
                continue
            mcu = self._mcus_by_id.get(PinStringMapper.from_string(step_pin).mcu_id)
            if mcu is None:
                continue
            resolved = CapabilityClass.for_connection(mcu.get("connection"))
            if resolved is not None:
                return resolved
        return CapabilityClass.STEP_DIR

    # -- pass 1: components ---------------------------------------------- #

    def _component_fragments(self, capability_class: CapabilityClass) -> list[HalFragment]:
        mapper = _STEPPER_MAPPERS.get(capability_class, StepperHalMapper)
        fragments: list[HalFragment] = []
        for axis in self._payload.get("axes", []):
            joints = [
                self._joints_by_number[n]
                for n in axis.get("joint_numbers", [])
                if n in self._joints_by_number
            ]
            if not joints:
                continue
            endstop = self._endstops_by_id.get(axis.get("endstop"))
            fragments.append(mapper.to_fragment(axis, joints, endstop))
        return fragments

    def _spindle_fragments(self) -> list[HalFragment]:
        """One fragment per digital spindle — independent of motion class.

        A spindle carries its own MCU (a VFD, an EtherCAT drive); it is
        never dispatched through a stepper mapper, and its presence or
        absence has no bearing on which stepper mapper the joints get.
        """
        return [
            DigitalSpindleHalMapper.to_fragment(tool)
            for tool in self._payload.get("tools", [])
            if isinstance(tool, dict) and tool.get("type") == "spindle_digital"
        ]

    # -- firmware sidecars -------------------------------------------------- #

    @staticmethod
    def _render_firmware_configs(fragment: HalFragment) -> None:
        """Group every :class:`FirmwareModuleRequest` by MCU into ``config_<id>.txt``.

        Cross-fragment aggregation (a Remora machine's joints and its
        endstops contribute modules from different mappers) is exactly
        what the assembler exists to coordinate — no single mapper sees
        the whole board's module list.
        """
        by_mcu: dict[str, list[dict[str, object]]] = {}
        for request in fragment.firmware_modules:
            by_mcu.setdefault(request.mcu_id, []).append(request.module)

        for mcu_id, modules in by_mcu.items():
            config = {
                "Thread": {
                    "Base": {"Frequency": _FIRMWARE_BASE_HZ},
                    "Servo": {"Frequency": _FIRMWARE_SERVO_HZ},
                },
                "Modules": modules,
            }
            fragment.files[f"config_{mcu_id}.txt"] = json.dumps(config, indent=2)

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

    def _route(self, requests: list[PinRequest]) -> tuple[list[HalFragment], list[HalFragment]]:
        by_mcu: dict[str, list[PinRequest]] = {}
        for request in requests:
            by_mcu.setdefault(request.pin.mcu_id, []).append(request)

        bases: list[HalFragment] = []
        routes: list[HalFragment] = []
        for mcu_id, mcu_requests in by_mcu.items():
            mcu = self._mcus_by_id.get(mcu_id)
            if mcu is None:
                continue  # E_UNKNOWN_MCU is the validator's job, not this one's.
            router = _ROUTERS.get(mcu.get("connection"))
            if router is None:
                raise UnsupportedMcuError(
                    f"no HAL router implemented yet for MCU {mcu_id!r} "
                    f"(connection={mcu.get('connection')!r})"
                )
            bases.append(router.base_fragment(mcu))
            routes.append(router.route(mcu_requests))
        return bases, routes


def assemble_machine(payload: dict[str, Any]) -> HalFragment:
    """Convenience wrapper — one call, the fully joined fragment."""
    return HalAssembler(payload).assemble()


__all__ = ["HalAssembler", "UnsupportedMcuError", "assemble_machine"]
