"""Joint + axis -> :class:`HalFragment` (`.agent/component/stepper.md`).

Class A only (software `stepgen`) for this pass — see
`.agent/component/README.md` § 2. A class B/C machine needs a
different per-joint body (position-command, or a hard reject); that
mapper lands when Phase 2/3 needs it, not here.

Home-switch wiring is resolved per **joint**, not once per axis: a
dual-motor (gantry) axis's second stepper can declare its own,
distinct switch (`hardware_json_generator.py`'s per-joint `endstop`
field) — sharing one switch across every joint on the axis would
leave that second switch permanently unwired, which is exactly what
used to happen (a real HAL bug: LinuxCNC homes a gantry expecting
independent switches per joint so it can square the gantry; blinding
one motor to the other's switch causes an immediate position error
during the latch phase). A joint with no switch of its own falls back
to its axis's `endstop` — the common case (a single-joint axis, or a
gantry whose second motor genuinely shares one physical switch)
behaves exactly as before.

Two axes can also share one physical endstop (PrintNC-WEBGUI's X and
Z both home off "home-xz") — `stepper.md` documents `net
<axis>-home-sw => joint.N.home-sw-in` once per (axis, joint) pair.
The signal name is derived from the **endstop's own id**
(`<endstop_id>-sw`), not the axis id — two axes (or two joints)
referencing the same endstop id then naturally produce the same
signal name, so they collapse onto one writer with two-or-more
readers instead of two writers fighting over one physical pin. The
assembler is what actually de-duplicates the resulting
:class:`PinRequest` (same signal requested twice) down to a single
route.
"""

from __future__ import annotations

from typing import Any

from mappers.machineconfig import PinStringMapper
from models.machineconfig.hal_fragment_models import HalFragment, PinRequest, PinRole

#: LinuxCNC `stepgen` defaults PrintNC-WEBGUI's Machine.hal uses for
#: every joint — see stepper.md § 3. Not user-configurable yet; every
#: profile in the repo before this pass used exactly these.
_STEPLEN_NS = 1
_STEPSPACE_NS = 0
_DIRHOLD_NS = 39000
_DIRSETUP_NS = 39000


class StepperHalMapper:
    """Per-axis HAL: stepgen config, position loop, step/dir/enable, home."""

    @staticmethod
    def to_fragment(
        axis: dict[str, Any],
        joints: list[dict[str, Any]],
        endstops_by_id: dict[str, dict[str, Any]],
    ) -> HalFragment:
        fragment = HalFragment()
        axis_id = str(axis["id"])
        axis_endstop_id = axis.get("endstop")
        requested_endstop_ids: set[str] = set()

        for index, joint in enumerate(joints, start=1):
            StepperHalMapper._joint(fragment, axis_id, joint, index)
            # This joint's own switch first; a joint with none of its
            # own (the common case) shares the axis's.
            endstop_id = joint.get("endstop") or axis_endstop_id
            endstop = endstops_by_id.get(endstop_id) if endstop_id else None
            if endstop is None:
                continue
            endstop_signal = f"{endstop['id']}-sw"
            fragment.nets.append(
                f"net {endstop_signal} => joint.{joint['joint_number']}.home-sw-in"
            )
            if endstop["id"] in requested_endstop_ids:
                continue
            requested_endstop_ids.add(endstop["id"])
            fragment.requests.append(
                PinRequest(
                    signal=endstop_signal,
                    role=PinRole.ENDSTOP,
                    pin=PinStringMapper.from_string(endstop["pin"]),
                    owner=str(endstop["id"]),
                )
            )

        return fragment

    @staticmethod
    def _joint(fragment: HalFragment, axis_id: str, joint: dict[str, Any], index: int) -> None:
        n = joint["joint_number"]
        joint_id = str(joint["id"])
        # A dual-motor (gantry) axis has more than one joint sharing
        # one `axis_id` — the first joint keeps the plain `<axis>pos-
        # cmd`/`<axis>pos-fb` names, but every joint after it must get
        # its own suffix (`y2pos-cmd`, `y3pos-cmd`, ...) or two
        # different `joint.N.motor-pos-cmd` writers collide on one
        # signal name, which HAL rejects outright ("signal already has
        # a writer") — real reference machines (PrintNC-V3.hal) use
        # exactly this `y`/`y2` split for their dual-Y gantry.
        pos_prefix = axis_id if index == 1 else f"{axis_id}{index}"

        fragment.setp.extend(
            [
                f"setp stepgen.{n}.position-scale [JOINT_{n}]SCALE",
                f"setp stepgen.{n}.steplen {_STEPLEN_NS}",
                f"setp stepgen.{n}.stepspace {_STEPSPACE_NS}",
                f"setp stepgen.{n}.dirhold {_DIRHOLD_NS}",
                f"setp stepgen.{n}.dirsetup {_DIRSETUP_NS}",
                f"setp stepgen.{n}.maxaccel [JOINT_{n}]STEPGEN_MAXACCEL",
            ]
        )
        fragment.nets.extend(
            [
                f"net {pos_prefix}pos-cmd joint.{n}.motor-pos-cmd => stepgen.{n}.position-cmd",
                f"net {pos_prefix}pos-fb stepgen.{n}.position-fb => joint.{n}.motor-pos-fb",
            ]
        )

        StepperHalMapper._pin_export(fragment, joint, "step_pin", PinRole.STEP, joint_id, n)
        StepperHalMapper._pin_export(fragment, joint, "dir_pin", PinRole.DIR, joint_id, n)

        # This net is what actually turns the stepgen on — without it,
        # `stepgen.N.enable` is never driven, the stepgen never runs,
        # and `position-fb` stays frozen at 0 while `position-cmd`
        # moves the instant a joint is commanded (homing or a jog):
        # within milliseconds that gap exceeds FERROR and LinuxCNC
        # throws a position error before a single real step happens.
        # Unconditional, unlike the PinRequest below: a joint with no
        # separate PHYSICAL enable pin (a real, verified working
        # PrintNC-WEBGUI machine only wires one for X; Y/Y1/Z have
        # none) still needs LinuxCNC's own amp-enable-out driving the
        # stepgen internally — that requirement doesn't depend on
        # whether a hardware pin is also being routed for it.
        fragment.nets.append(
            f"net {joint_id}-enable joint.{n}.amp-enable-out => stepgen.{n}.enable"
        )

        enable_pin = joint.get("enable_pin")
        if enable_pin:
            fragment.requests.append(
                PinRequest(
                    signal=f"{joint_id}-enable",
                    role=PinRole.ENABLE,
                    pin=PinStringMapper.from_string(enable_pin),
                    owner=joint_id,
                )
            )

    @staticmethod
    def _pin_export(
        fragment: HalFragment,
        joint: dict[str, Any],
        field: str,
        role: PinRole,
        joint_id: str,
        joint_number: int,
    ) -> None:
        raw = joint.get(field)
        if not raw:
            return
        stepgen_pin = "step" if role is PinRole.STEP else "dir"
        signal = f"{joint_id}-{role.value}"
        fragment.nets.append(f"net {signal} <= stepgen.{joint_number}.{stepgen_pin}")
        fragment.requests.append(
            PinRequest(signal=signal, role=role, pin=PinStringMapper.from_string(raw), owner=joint_id)
        )


__all__ = ["StepperHalMapper"]
