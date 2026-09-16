"""Pause & Inspect (Z-axis lift + spindle inhibit) -> `webgui_connections.hal`.

`ProgramService.pause_inspect()`/`resume_program()` (`backend/machine/
services/ProgramService.py`) drive `webgui.inspect-z-lift`/`webgui.
inspect-spindle-inhibit` as plain 0/1 toggles — the actual Z lift
*distance* is configured once here via `axis.z.eoffset-scale` (1 count
= `eoffset-scale` machine units), never sent from Python. This mirrors
`EstopWebguiMapper`: a machine-level safety feature, not tied to any
`hardware.json` tool entry, so `to_lines()` takes no arguments and is
called unconditionally — every machine has a Z axis (`[machine]`
compilation only accepts `kinematics: cartesian`).

`axis.z.eoffset-clear` is wired from `iocontrol.0.user-enable-out`
(LinuxCNC's own "machine is enabled" bit, always present) rather than
`[estop]`'s optional `estop-out` signal (`EstopHalMapper`) — that
signal only exists when the operator declared `[estop].out_pin`, and
a dangling net on a machine without one would fail to load. Using the
native `iocontrol` pin directly means the eoffset clears on E-stop (or
any other loss of machine-enable) on every machine, no `[estop]`
configuration required.
"""

from __future__ import annotations


class PauseInspectWebguiMapper:
    """`net`/`setp` lines wiring the Pause & Inspect safety feature."""

    #: 1 count = this many machine units (mm) of Z lift. A bare
    #: on/off toggle from Python times this scale into the actual
    #: lift distance — tune per machine by hand-editing this line in
    #: the generated `webgui_connections.hal` (preserved on regenerate,
    #: same as every other operator hand-edit).
    _EOFFSET_SCALE = 1.0

    @staticmethod
    def to_lines() -> list[str]:
        return [
            "# Pause & Inspect (external offsets & spindle inhibit)",
            "net inspect-spindle-inhibit webgui.inspect-spindle-inhibit => motion.spindle-inhibit",
            "",
            "setp axis.z.eoffset-enable 1",
            f"setp axis.z.eoffset-scale {PauseInspectWebguiMapper._EOFFSET_SCALE}",
            "net inspect-eoffset-clear <= iocontrol.0.user-enable-out",
            "net inspect-eoffset-clear => axis.z.eoffset-clear",
            "",
            "net inspect-z-lift webgui.inspect-z-lift => axis.z.eoffset-counts",
            "",
        ]


__all__ = ["PauseInspectWebguiMapper"]
