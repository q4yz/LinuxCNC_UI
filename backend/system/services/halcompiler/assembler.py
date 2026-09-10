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
from models.machineconfig.hal_fragment_models import HalFragment, PinRequest, combine
from models.machineconfig.pin_models import CapabilityClass

from .components.DigitalSpindleHalMapper import DigitalSpindleHalMapper
from .components.HeaterHalMapper import HeaterHalMapper
from .components.MotionSystemHalMapper import MotionSystemHalMapper
from .components.RemoraDriverFirmwareMapper import RemoraDriverFirmwareMapper
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

#: `config.txt`'s `"Board"` when the MCU declares none — the real
#: reference config (`machine_config/example/ender3/config.txt`) uses
#: this exact name, and `board` is never autofilled onto the MCU
#: record itself (`.agent/component/mcu_spi_remora.md` § 1) — this
#: fallback is `config.txt`-only, not something a `hardware.json`
#: reader would ever see.
_DEFAULT_FIRMWARE_BOARD = "BIGTREETECH OCTOPUS"


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
        self._sensors_by_id = {
            s["id"]: s for s in payload.get("temperature_sensors", []) if s.get("id")
        }
        self._fans_by_id = {f["id"]: f for f in payload.get("fans", []) if f.get("id")}
        self._drivers_by_id = {d["id"]: d for d in payload.get("drivers", []) if d.get("id")}
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
            + self._driver_fragments(capability_class)
        )
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

    def _motion_mcu_ids(self) -> set[str]:
        """Every MCU that owns at least one joint's ``step_pin``.

        Used by ``_route`` to force that MCU's ``base_fragment()`` to
        run even with zero routed :class:`PinRequest`\\ s — see the
        call site for why that matters on class B.
        """
        ids: set[str] = set()
        for joint in self._joints_by_number.values():
            step_pin = joint.get("step_pin")
            if step_pin:
                ids.add(PinStringMapper.from_string(step_pin).mcu_id)
        return ids

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
        for tool in self._payload.get("tools", []):
            if not isinstance(tool, dict) or tool.get("type") not in ("extruder", "heated_bed"):
                continue
            sensor = self._sensors_by_id.get(tool.get("sensor"))
            fan = self._fans_by_id.get(tool.get("fan"))
            fragments.append(HeaterHalMapper.to_fragment(tool, sensor, fan))
        return fragments

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
        joints = list(self._joints_by_number.values())
        fragment = RemoraDriverFirmwareMapper.to_fragment(joints, self._drivers_by_id)
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

        Root shape is ``{"Board": ..., "Modules": [...]}`` — verified
        against the real, working
        ``machine_config/example/ender3/config.txt``, which has no
        top-level ``"Thread"`` frequency block at all (that was this
        function's own earlier, unverified guess).
        """
        by_mcu: dict[str, list[dict[str, object]]] = {}
        for request in fragment.firmware_modules:
            by_mcu.setdefault(request.mcu_id, []).append(request.module)

        for mcu_id, modules in by_mcu.items():
            mcu = self._mcus_by_id.get(mcu_id) or {}
            config: dict[str, Any] = {
                "Board": mcu.get("board") or _DEFAULT_FIRMWARE_BOARD,
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
