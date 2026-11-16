"""Input shaping, skew correction and the resonance test signal on the X / Y
joints -> the Remora ``jointshape`` component (Remora-m8p
``LinuxCNC/Components/JointShape``, installed by
``scripts/install_hal_components.sh``).

Emitted on a Cartesian Remora machine with ``[input_shaper]``,
``[skew_correction]`` or ``[adxl345]``: one instance per X / Y joint, between
the joint and its step generator (`RemoraStepperHalMapper` leaves those nets
out)::

    loadrt jointshape names=shape-j0,shape-j1
    addf shape-j0 servo-thread
    setp shape-j0.shaper-type 2            # zv 1, mzv 2, zvd 3, ei 4
    setp shape-j0.damping 0.1
    net j0pos-cmd joint.0.motor-pos-cmd => shape-j0.pos-cmd-in
    net j0pos-cmd-shaped shape-j0.pos-cmd-out => remora.joint.0.pos-cmd
    net j0pos-fb remora.joint.0.pos-fb => shape-j0.pos-fb-in
    net j0pos-fb-shaped shape-j0.pos-fb-out => joint.0.motor-pos-fb
    net j1pos-cmd => shape-j0.skew-ref     # X gets x - factor * y

The live values come from the UI (``webgui_connections.hal``): the shaper
frequencies (``webgui.shaper-freq-x`` / ``-y``), the skew factor
(``webgui.skew-xy``) and the resonance test (``webgui.resonance-amp-x`` /
``-y``, ``webgui.resonance-freq``) — ``ShaperService`` starts them at the
profile's values. Not on CoreXY (its X / Y joints feed the CoreXY mixing).
"""
from __future__ import annotations

from typing import Any

from models.machineconfig.HalFragmentModels import SERVO_THREAD, Addf, HalFragment
from models.machineconfig.PinModels import CapabilityClass

SHAPER_TYPES = {"zv": 1, "mzv": 2, "zvd": 3, "ei": 4}


def _component(joint: int) -> str:
    return f"shape-j{joint}"


def shaped_joints(payload: dict[str, Any]) -> dict[int, str]:
    """Joint number -> ``"x"`` / ``"y"`` for the joints that get a
    ``jointshape`` (empty when the machine wants none or cannot have it)."""
    wanted = any(isinstance(payload.get(k), dict) for k in ("input_shaper", "skew_correction", "adxl345"))
    if not wanted or payload.get("kinematics") == "corexy":
        return {}
    from ..HalAssembler import HalAssembler

    if HalAssembler(payload)._capability_class() is not CapabilityClass.POSITION:
        return {}
    joints: dict[int, str] = {}
    for axis in payload.get("axes") or []:
        letter = str(axis.get("id", "")).lower()
        if letter in ("x", "y"):
            for number in axis.get("joint_numbers") or []:
                joints[int(number)] = letter
    return joints


class JointShapeHalMapper:
    @staticmethod
    def to_fragment(payload: dict[str, Any], joints: dict[int, str]) -> HalFragment:
        fragment = HalFragment()
        if not joints:
            return fragment
        shaper = payload.get("input_shaper") or {}
        names = ",".join(_component(n) for n in sorted(joints))
        fragment.loadrt.append(f"loadrt jointshape names={names}")
        y_joints = sorted(n for n, letter in joints.items() if letter == "y")
        for n in sorted(joints):
            letter = joints[n]
            comp = _component(n)
            fragment.addf.append(Addf(comp, SERVO_THREAD, order=2))
            fragment.setp.append(f"setp {comp}.shaper-type {SHAPER_TYPES.get(str(shaper.get(f'type_{letter}', 'mzv')), 2)}")
            fragment.setp.append(f"setp {comp}.damping {float(shaper.get(f'damping_{letter}', 0.1)):g}")
            fragment.nets.extend([
                f"net j{n}pos-cmd joint.{n}.motor-pos-cmd => {comp}.pos-cmd-in",
                f"net j{n}pos-cmd-shaped {comp}.pos-cmd-out => remora.joint.{n}.pos-cmd",
                f"net j{n}pos-fb remora.joint.{n}.pos-fb => {comp}.pos-fb-in",
                f"net j{n}pos-fb-shaped {comp}.pos-fb-out => joint.{n}.motor-pos-fb",
            ])
            if letter == "x" and y_joints:
                fragment.nets.append(f"net j{y_joints[0]}pos-cmd => {comp}.skew-ref")
        return fragment

    @staticmethod
    def webgui_lines(joints: dict[int, str]) -> list[str]:
        if not joints:
            return []
        lines = ["# Input shaper / skew / resonance test (machine.hal's shape-j<n>)"]
        for letter in ("x", "y"):
            comps = [_component(n) for n, l in sorted(joints.items()) if l == letter]
            if not comps:
                continue
            lines.append(f"net shaper-freq-{letter} webgui.shaper-freq-{letter} => " + " ".join(f"{c}.shaper-freq" for c in comps))
            lines.append(f"net resonance-amp-{letter} webgui.resonance-amp-{letter} => " + " ".join(f"{c}.test-amp" for c in comps))
            if letter == "x":
                lines.append("net skew-xy webgui.skew-xy => " + " ".join(f"{c}.skew-factor" for c in comps))
        lines.append("net resonance-freq webgui.resonance-freq => " + " ".join(f"{_component(n)}.test-freq" for n in sorted(joints)))
        lines.append("")
        return lines


__all__ = ["JointShapeHalMapper", "SHAPER_TYPES", "shaped_joints"]
