"""PauseInspectWebguiMapper — `webgui_connections.hal` binding for the
Z-axis lift + spindle inhibit safety feature.

Machine-level like `EstopWebguiMapper`, but unlike it, `to_lines()`
takes the `estop` dict: the eoffset-clear safety net must not
double-link `iocontrol.0.user-enable-out` onto a second signal when
`[estop].out_pin` already claims it via `EstopHalMapper`'s `estop-out`
(a genuine HAL "pin already linked" load failure, not a soft
conflict — the same class of bug the mux2 spindle fix routed around).
Also covers the `webgui.inspect-z-lift` (bit) -> `axis.z.eoffset-counts`
(s32) type mismatch, the same `conv_bit_*` idiom `HeaterHalMapper`
already uses for its own bit -> float watermark branch, and the
spindle-inhibit target being `spindle.0.inhibit` (per-spindle, per a
real `halcmd show`) rather than a global `motion.spindle-inhibit`
pin, which does not exist.
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


def test_eoffset_clears_from_the_native_iocontrol_pin_when_no_estop_out_pin():
    """No `[estop].out_pin` declared -> nothing else claims
    `iocontrol.0.user-enable-out`, so linking it directly is safe."""
    lines = PauseInspectWebguiMapper.to_lines({})
    assert "net inspect-eoffset-clear <= iocontrol.0.user-enable-out" in lines
    assert "net inspect-eoffset-clear => axis.z.eoffset-clear" in lines
    assert not any("estop-out" in line for line in lines)


def test_eoffset_clears_from_the_existing_estop_out_signal_when_declared():
    """`[estop].out_pin` declared -> `EstopHalMapper` already links
    `iocontrol.0.user-enable-out` to the `estop-out` signal in
    `machine.hal`; re-linking that same physical pin to a second
    signal here would be a HAL load-time "pin already linked" error.
    Reading the existing `estop-out` signal (a second reader) is the
    only safe option."""
    lines = PauseInspectWebguiMapper.to_lines({"out_pin": "par0:14"})
    assert "net estop-out => axis.z.eoffset-clear" in lines
    assert not any("iocontrol.0.user-enable-out" in line for line in lines)


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
    """Same `estop` input -> identical output every time."""
    assert PauseInspectWebguiMapper.to_lines({}) == PauseInspectWebguiMapper.to_lines({})
    assert PauseInspectWebguiMapper.to_lines(None) == PauseInspectWebguiMapper.to_lines({})
