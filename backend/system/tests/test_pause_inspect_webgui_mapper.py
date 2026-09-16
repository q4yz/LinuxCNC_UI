"""PauseInspectWebguiMapper — `webgui_connections.hal` binding for the
Z-axis lift + spindle inhibit safety feature.

Machine-level and unconditional, same shape as `EstopWebguiMapper`: no
arguments, output never varies per machine. Covers three fixes to a
previous version, each only observable on a real LinuxCNC session,
never from string-content assertions alone:

* the spindle-inhibit target being `spindle.0.inhibit` (per-spindle,
  per a real `halcmd show`) rather than a global `motion.spindle-inhibit`
  pin, which does not exist;
* the `webgui.inspect-z-lift` (bit) -> `axis.z.eoffset-counts` (s32)
  type mismatch, the same `conv_bit_*` idiom `HeaterHalMapper` already
  uses for its own bit -> float watermark branch;
* `axis.z.eoffset-clear`'s source being `halui.estop.is-activated`
  (TRUE only while E-stop actually is active) rather than `estop-out`
  / `iocontrol.0.user-enable-out` (TRUE while the machine is healthy —
  the *opposite* polarity, which continuously crushed the Z lift back
  to 0 every servo cycle; a real bug, manually verified and fixed).
"""

from __future__ import annotations

from services.halcompiler.components.PauseInspectWebguiMapper import PauseInspectWebguiMapper


def test_binds_spindle_inhibit_into_the_per_spindle_pin():
    """`motion.spindle-inhibit` does not exist — a real `halcmd show`
    confirms the pin is `spindle.N.inhibit`, indexed the same way
    every other spindle pin in this compiler already is
    (`DigitalSpindleHalMapper`'s `spindle.{n}.speed-out`/`.forward`/
    `.at-speed`)."""
    lines = PauseInspectWebguiMapper.to_lines()
    assert "net inspect-spindle-inhibit webgui.inspect-spindle-inhibit => spindle.0.inhibit" in lines
    assert not any("motion.spindle-inhibit" in line for line in lines)


def test_enables_the_z_eoffset_stage_with_a_configurable_scale():
    lines = PauseInspectWebguiMapper.to_lines()
    assert "setp axis.z.eoffset-enable 1" in lines
    assert "setp axis.z.eoffset-scale 1.0" in lines


def test_eoffset_clears_only_while_estop_is_actually_active():
    """`halui.estop.is-activated` is TRUE only while E-stop is
    engaged — the correct polarity for "clear the lift on E-stop".
    `estop-out`/`iocontrol.0.user-enable-out` (TRUE while healthy, the
    opposite) must never appear here again — that was the real,
    manually-verified bug this replaced."""
    lines = PauseInspectWebguiMapper.to_lines()
    assert "net estop-is-active halui.estop.is-activated => axis.z.eoffset-clear" in lines
    assert not any("iocontrol.0.user-enable-out" in line for line in lines)
    assert not any("estop-out" in line for line in lines)


def test_z_lift_is_converted_from_bit_to_s32_before_eoffset_counts():
    """`axis.z.eoffset-counts` is a HAL `s32` pin — linking the `bit`
    `webgui.inspect-z-lift` straight into it is a load-time type
    mismatch. `conv_bit_s32` bridges it, same idiom `HeaterHalMapper`
    uses for its own bit -> float branch."""
    lines = PauseInspectWebguiMapper.to_lines()
    assert "loadrt conv_bit_s32 names=inspect-z-lift-conv" in lines
    assert "addf inspect-z-lift-conv servo-thread" in lines
    assert "net inspect-z-lift-bit webgui.inspect-z-lift => inspect-z-lift-conv.in" in lines
    assert "net inspect-z-lift-s32 inspect-z-lift-conv.out => axis.z.eoffset-counts" in lines
    assert not any(
        "webgui.inspect-z-lift => axis.z.eoffset-counts" in line for line in lines
    ), "webgui.inspect-z-lift (bit) must never net straight onto eoffset-counts (s32)"


def test_output_is_stable_regardless_of_call_site():
    """No parameters — the binding never varies per machine."""
    assert PauseInspectWebguiMapper.to_lines() == PauseInspectWebguiMapper.to_lines()
