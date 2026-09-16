"""PauseInspectWebguiMapper — `webgui_connections.hal` binding for the
Z-axis lift + spindle inhibit safety feature.

Machine-level and unconditional, same shape as `EstopWebguiMapper`
(`test_estop_webgui_mapper.py`): no arguments, output never varies
per machine.
"""

from __future__ import annotations

from services.halcompiler.components.PauseInspectWebguiMapper import PauseInspectWebguiMapper


def test_binds_spindle_inhibit_straight_into_motion():
    lines = PauseInspectWebguiMapper.to_lines()
    assert "net inspect-spindle-inhibit webgui.inspect-spindle-inhibit => motion.spindle-inhibit" in lines


def test_enables_the_z_eoffset_stage_with_a_configurable_scale():
    lines = PauseInspectWebguiMapper.to_lines()
    assert "setp axis.z.eoffset-enable 1" in lines
    assert "setp axis.z.eoffset-scale 1.0" in lines


def test_eoffset_clears_from_the_native_iocontrol_enable_pin():
    """Wired from `iocontrol.0.user-enable-out` (always present), not
    `[estop]`'s optional `estop-out` signal — a machine without
    `[estop].out_pin` declared must still get a working clear."""
    lines = PauseInspectWebguiMapper.to_lines()
    assert "net inspect-eoffset-clear <= iocontrol.0.user-enable-out" in lines
    assert "net inspect-eoffset-clear => axis.z.eoffset-clear" in lines


def test_binds_z_lift_into_eoffset_counts():
    lines = PauseInspectWebguiMapper.to_lines()
    assert "net inspect-z-lift webgui.inspect-z-lift => axis.z.eoffset-counts" in lines


def test_output_is_stable_regardless_of_call_site():
    """No parameters — the binding never varies per machine."""
    assert PauseInspectWebguiMapper.to_lines() == PauseInspectWebguiMapper.to_lines()
