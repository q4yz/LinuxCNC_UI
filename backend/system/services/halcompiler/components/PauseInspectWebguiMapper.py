"""Pause & Inspect (Z-axis lift + spindle inhibit) -> `webgui_connections.hal`.

`ProgramService.pause_inspect()`/`resume_program()` (`backend/machine/
services/ProgramService.py`) drive `webgui.inspect-z-lift`/`webgui.
inspect-spindle-inhibit` as plain 0/1 toggles — the actual Z lift
*distance* is configured once here via `axis.z.eoffset-scale` (1 count
= `eoffset-scale` machine units), never sent from Python. This mirrors
`EstopWebguiMapper`: a machine-level safety feature, not tied to any
`hardware.json` tool entry, called unconditionally whenever `estop` is
present (every machine with a Z axis gets it — `[machine]` compilation
only accepts `kinematics: cartesian`). No longer preserved across a
regenerate, like every other file `generate_machine_templates` writes
(see its own module docstring) — a fix here reaches every existing
machine the next time it's (re)generated.

`[AXIS_Z] OFFSET_AV_RATIO` (`ini_template_generator.py`'s
`_OFFSET_AV_RATIO`) has to be set too, or this wiring is inert — a
correctly-netted `eoffset-counts` still never actually moves the axis
without a nonzero velocity/accel budget reserved for external-offset
motion.

Two HAL hazards this mapper routes around, both only observable on a
real LinuxCNC session (never at Python string-generation time or in a
unit test asserting on string content alone):

* **Spindle inhibit is per-spindle, not global.** There is no
  `motion.spindle-inhibit` pin — a real `halcmd show` confirms it is
  `spindle.N.inhibit` (`DigitalSpindleHalMapper` already nets every
  other spindle pin the same indexed way: `spindle.{n}.speed-out`,
  `.forward`, `.at-speed`, ...). This mapper has no visibility into
  which spindle(s) a machine declares, so it targets `spindle.0.inhibit`
  — correct for the single-spindle case every real profile in this
  repo has today; a genuine multi-spindle machine needs this extended
  to inhibit every configured spindle, an honest gap, not a silent one.
* **`axis.z.eoffset-counts` is a HAL `s32` pin, not `bit`.** Linking
  `webgui.inspect-z-lift` (a `bit`) straight into it is a HAL load-time
  "pin type mismatch" — the exact same class of error `HeaterHalMapper`
  already routes around for its watermark branch's `comp.out` (`bit`)
  -> a `float` duty-cycle channel (`.agent/component/heater.md` § 3,
  `"comp.out is a HAL BIT ... Linking a bit pin to a float pin is a
  HAL load-time type error"`), via the exact same `conv_bit_*` idiom
  used here (`conv_bit_s32` instead of `conv_bit_float`).

`axis.z.eoffset-clear` is wired from `halui.estop.is-activated`, a
standard HALUI status pin, always present — NOT from `estop-out`
(`iocontrol.0.user-enable-out`, `EstopHalMapper`) as an earlier version
of this mapper had it. That was a real, manually-verified polarity
bug: `iocontrol.0.user-enable-out` is TRUE while the machine is
powered on and healthy, and FALSE on E-stop — the *opposite* of what
"clear on E-stop" needs. Wired that way, `eoffset-clear` was asserted
continuously during normal operation, crushing the Z lift back to 0
every servo cycle — the feature never actually lifted anything.
`halui.estop.is-activated` is TRUE only while E-stop actually is
active, the correct polarity, and (being a `halui` pin, not tied to
`[estop]`'s optional `out_pin`) needs no `estop`-dict branching the
way the old `estop-out` source did.
"""

from __future__ import annotations


class PauseInspectWebguiMapper:
    """`net`/`setp` lines wiring the Pause & Inspect safety feature."""

    #: 1 count = this many machine units (mm) of Z lift. A bare
    #: on/off toggle from Python times this scale into the actual
    #: lift distance — tune per machine by hand-editing this line in
    #: the generated `webgui_connections.hal`. Not preserved across a
    #: regenerate (see module docstring), so a machine-specific tweak
    #: here has to be re-applied after every regenerate.
    _EOFFSET_SCALE = 1.0

    #: `spindle.N.inhibit` is per-spindle (real `halcmd show` output
    #: confirmed there is no global `motion.spindle-inhibit`) — see
    #: module docstring for the single-spindle-only caveat.
    _SPINDLE_INDEX = 0

    @staticmethod
    def to_lines() -> list[str]:
        return [
            "# Pause & Inspect (external offsets & spindle inhibit)",
            f"net inspect-spindle-inhibit webgui.inspect-spindle-inhibit => spindle.{PauseInspectWebguiMapper._SPINDLE_INDEX}.inhibit",
            "",
            "setp axis.z.eoffset-enable 1",
            f"setp axis.z.eoffset-scale {PauseInspectWebguiMapper._EOFFSET_SCALE}",
            # TRUE only while E-stop actually is active — see module
            # docstring for why iocontrol.0.user-enable-out (estop-out)
            # is the wrong polarity for this.
            "net estop-is-active halui.estop.is-activated => axis.z.eoffset-clear",
            "",
            # axis.z.eoffset-counts is s32; webgui.inspect-z-lift is
            # bit — conv_bit_s32 is the same type-converter idiom
            # HeaterHalMapper already uses for its own bit -> float
            # watermark branch (see module docstring).
            "loadrt conv_bit_s32 names=inspect-z-lift-conv",
            "addf inspect-z-lift-conv servo-thread",
            "net inspect-z-lift-bit webgui.inspect-z-lift => inspect-z-lift-conv.in",
            "net inspect-z-lift-s32 inspect-z-lift-conv.out => axis.z.eoffset-counts",
            "",
        ]


__all__ = ["PauseInspectWebguiMapper"]
