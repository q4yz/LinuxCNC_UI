"""Joint + axis -> :class:`HalFragment` (`.agent/component/stepper.md`).

Class A only (software `stepgen`) for this pass — see
`.agent/component/README.md` § 2. A class B/C machine needs a
different per-joint body (position-command, or a hard reject); that
mapper lands when Phase 2/3 needs it, not here.

Operates per **axis**, not per joint, because the home-switch wiring
is axis-scoped: `stepper.md` documents `net <axis>-home-sw => joint.N
.home-sw-in` once per (axis, joint) pair, and two axes can share one
physical endstop (PrintNC-WEBGUI's X and Z both home off "home-xz").
The signal name is derived from the **endstop's own id**
(`<endstop_id>-sw`), not the axis id — two axes referencing the same
endstop id then naturally produce the same signal name, so they
collapse onto one writer with two readers instead of two writers
fighting over one physical pin. The assembler is what actually
de-duplicates the resulting :class:`PinRequest` (same signal requested
twice, once per axis) down to a single route.
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
        endstop: dict[str, Any] | None,
    ) -> HalFragment:
        fragment = HalFragment()
        axis_id = str(axis["id"])
        endstop_signal = f"{endstop['id']}-sw" if endstop else None

        for joint in joints:
            StepperHalMapper._joint(fragment, axis_id, joint)
            if endstop_signal is not None:
                fragment.nets.append(
                    f"net {endstop_signal} => joint.{joint['joint_number']}.home-sw-in"
                )

        if endstop is not None:
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
    def _joint(fragment: HalFragment, axis_id: str, joint: dict[str, Any]) -> None:
        n = joint["joint_number"]
        joint_id = str(joint["id"])

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
                f"net {axis_id}pos-cmd joint.{n}.motor-pos-cmd => stepgen.{n}.position-cmd",
                f"net {axis_id}pos-fb stepgen.{n}.position-fb => joint.{n}.motor-pos-fb",
            ]
        )

        StepperHalMapper._pin_export(fragment, joint, "step_pin", PinRole.STEP, joint_id, n)
        StepperHalMapper._pin_export(fragment, joint, "dir_pin", PinRole.DIR, joint_id, n)

        enable_pin = joint.get("enable_pin")
        if enable_pin:
            fragment.nets.append(
                f"net {joint_id}-enable joint.{n}.amp-enable-out => stepgen.{n}.enable"
            )
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
