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

Three HAL load-time hazards this mapper has to route around, each only
observable once the generated files are actually loaded on a real
LinuxCNC session (never at Python string-generation time, which is why
the unit tests alone did not catch any of them):

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
* **`axis.z.eoffset-clear`'s safety source can double-claim a pin.**
  `[estop]`'s optional `out_pin` (`EstopHalMapper`) already links
  `iocontrol.0.user-enable-out` to the `estop-out` signal when declared
  — a HAL pin can only ever belong to one signal, so this mapper must
  NOT also net `iocontrol.0.user-enable-out` onto a second signal of
  its own on a machine that declared one (a genuine "pin already
  linked" load failure, not a soft conflict — see `DigitalSpindleHalMapper.
  build_speed_command`'s docstring for the same class of bug in the
  spindle mux2 fix). `to_lines()` therefore takes the `estop` dict and
  reads the already-existing `estop-out` *signal* (a second reader,
  always legal) when `out_pin` is declared, falling back to linking
  `iocontrol.0.user-enable-out` directly — perfectly legal since
  nothing else claims that physical pin — only when it is not. A
  machine with neither still loads fine either way; `estop-out`
  existing with no reader, or a net with no writer, both just idle at
  their default value rather than failing to load — only a genuine
  double link on the same physical pin does that.
"""

from __future__ import annotations

from typing import Any


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
    def to_lines(estop: dict[str, Any] | None = None) -> list[str]:
        estop = estop or {}

        lines = [
            "# Pause & Inspect (external offsets & spindle inhibit)",
            f"net inspect-spindle-inhibit webgui.inspect-spindle-inhibit => spindle.{PauseInspectWebguiMapper._SPINDLE_INDEX}.inhibit",
            "",
            "setp axis.z.eoffset-enable 1",
            f"setp axis.z.eoffset-scale {PauseInspectWebguiMapper._EOFFSET_SCALE}",
        ]

        if estop.get("out_pin"):
            # estop-out already exists (EstopHalMapper, machine.hal)
            # and already claims iocontrol.0.user-enable-out as its
            # writer — read the existing signal, never re-link the
            # same physical pin onto a second signal of our own.
            lines.append("net estop-out => axis.z.eoffset-clear")
        else:
            # No [estop].out_pin declared, so nothing else claims this
            # pin — safe to link it directly.
            lines.extend(
                [
                    "net inspect-eoffset-clear <= iocontrol.0.user-enable-out",
                    "net inspect-eoffset-clear => axis.z.eoffset-clear",
                ]
            )

        lines.extend(
            [
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
        )

        return lines


__all__ = ["PauseInspectWebguiMapper"]
