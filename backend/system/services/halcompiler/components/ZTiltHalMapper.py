"""``[z_tilt]`` -> a per-motor offset in each Z joint's position loop
(`.agent/component/z_tilt.md` § 3).

LinuxCNC drives every joint of one axis together; Z tilt needs to move
one Z motor alone. So each Z joint's position command and feedback go
through LinuxCNC's ``offset`` component: the motor gets
``motor-pos-cmd + offset``, motion gets ``motor-pos-fb - offset`` back,
so the planner never sees the correction. The offset ramps to the
target the machine backend writes (``webgui.ztilt-<k>``) through a
``limit2`` at :data:`RAMP_MM_PER_S`, clamped to ``±max_adjust``.

Runs after the stepper mappers: it rewrites their two position nets per
Z joint (whichever driver they feed — ``remora.joint.N`` or
``stepgen.N``) rather than every stepper mapper knowing about it.
"""
from __future__ import annotations

from typing import Any

from models.machineconfig.HalFragmentModels import SERVO_THREAD, Addf, HalFragment

#: How fast a correction is applied (mm/s): slow enough for any driver.
RAMP_MM_PER_S = 2.0


def offset_name(index: int) -> str:
    return f"ztilt-{index}"


def ramp_name(index: int) -> str:
    return f"ztilt-ramp-{index}"


def target_pin(index: int) -> str:
    """The machine backend's pin (``webgui.<this>``) for motor ``index``."""
    return f"ztilt-{index}"


class ZTiltHalMapper:
    @staticmethod
    def apply(fragments: list[HalFragment], z_tilt: dict[str, Any]) -> HalFragment:
        """Splice the offsets into ``fragments`` (in place); the new
        components as their own fragment."""
        joints = [int(j) for j in z_tilt.get("joints") or []]
        limit = float(z_tilt.get("max_adjust") or 5.0)
        offsets = [offset_name(k) for k in range(len(joints))]
        ramps = [ramp_name(k) for k in range(len(joints))]
        fragment = HalFragment(
            loadrt=[f"loadrt offset names={','.join(offsets)}", f"loadrt limit2 names={','.join(ramps)}"],
        )
        for k, joint in enumerate(joints):
            offset, ramp = offsets[k], ramps[k]
            ZTiltHalMapper._splice(fragments, joint, offset)
            fragment.addf += [
                # Feedback right after the driver read (order 0), output
                # after the motion controller (order 1), before the write.
                Addf(f"{offset}.update-feedback", SERVO_THREAD, order=0),
                Addf(ramp, SERVO_THREAD, order=1),
                Addf(f"{offset}.update-output", SERVO_THREAD, order=1),
            ]
            fragment.setp += [
                f"setp {ramp}.maxv {RAMP_MM_PER_S:g}",
                f"setp {ramp}.min {-limit:g}",
                f"setp {ramp}.max {limit:g}",
            ]
            fragment.nets.append(f"net ztilt-{k}-offset {ramp}.out => {offset}.offset")
        return fragment

    @staticmethod
    def _splice(fragments: list[HalFragment], joint: int, offset: str) -> None:
        cmd_pin, fb_pin = f"joint.{joint}.motor-pos-cmd", f"joint.{joint}.motor-pos-fb"
        found = {"cmd": False, "fb": False}
        for fragment in fragments:
            rewritten: list[str] = []
            for line in fragment.nets:
                words = line.split()
                # net <sig> joint.N.motor-pos-cmd => <driver input...>
                if len(words) >= 5 and words[0] == "net" and words[2] == cmd_pin and words[3] == "=>":
                    signal = words[1]
                    rewritten.append(f"net {signal} {cmd_pin} => {offset}.in")
                    rewritten.append(f"net {signal}-tilt {offset}.out => {' '.join(words[4:])}")
                    found["cmd"] = True
                # net <sig> <driver output> => joint.N.motor-pos-fb
                elif len(words) == 5 and words[0] == "net" and words[3] == "=>" and words[4] == fb_pin:
                    signal = words[1]
                    rewritten.append(f"net {signal}-raw {words[2]} => {offset}.fb-in")
                    rewritten.append(f"net {signal} {offset}.fb-out => {fb_pin}")
                    found["fb"] = True
                else:
                    rewritten.append(line)
            fragment.nets = rewritten
        if not all(found.values()):
            raise ValueError(f"z_tilt: no position command / feedback nets for joint {joint} to put the offset in")


class ZTiltWebguiMapper:
    """The machine backend's target pin per motor onto its ramp."""

    @staticmethod
    def to_lines(z_tilt: dict[str, Any]) -> list[str]:
        lines = ["# Z tilt: per-motor offset targets"]
        for k in range(len(z_tilt.get("joints") or [])):
            lines.append(f"net ztilt-{k}-target webgui.{target_pin(k)} => {ramp_name(k)}.in")
        return lines + [""]


__all__ = ["RAMP_MM_PER_S", "ZTiltHalMapper", "ZTiltWebguiMapper", "offset_name", "ramp_name", "target_pin"]
