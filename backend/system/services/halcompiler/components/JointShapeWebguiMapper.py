"""Input shaper / skew / resonance test -> ``webgui_connections.hal``:
the machine backend's ``ShaperService`` pins onto each ``shape-j<n>``."""
from __future__ import annotations

from .JointShapeHalMapper import JointShapeHalMapper


class JointShapeWebguiMapper:
    @staticmethod
    def to_lines(joints: dict[int, str]) -> list[str]:
        if not joints:
            return []
        lines = ["# Input shaper / skew / resonance test (machine.hal's shape-j<n>)"]
        for letter in ("x", "y"):
            comps = [JointShapeHalMapper.component(n) for n, l in sorted(joints.items()) if l == letter]
            if not comps:
                continue
            lines.append(f"net shaper-freq-{letter} webgui.shaper-freq-{letter} => " + " ".join(f"{c}.shaper-freq" for c in comps))
            lines.append(f"net resonance-amp-{letter} webgui.resonance-amp-{letter} => " + " ".join(f"{c}.test-amp" for c in comps))
            if letter == "x":
                lines.append("net skew-xy webgui.skew-xy => " + " ".join(f"{c}.skew-factor" for c in comps))
        lines.append("net resonance-freq webgui.resonance-freq => " + " ".join(f"{JointShapeHalMapper.component(n)}.test-freq" for n in sorted(joints)))
        lines.append("")
        return lines


__all__ = ["JointShapeWebguiMapper"]
