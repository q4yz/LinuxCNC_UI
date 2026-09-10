"""EstopWebguiMapper — `webgui_connections.hal` binding for the E-stop's UI trigger.

`webgui.estop` is already a clean 0 -> 1 -> 0 edge by the time HAL
sees it — `StateService.activate_estop()` (`machine/services/
StateService.py`) generates the pulse itself now, so this is a plain
passthrough net, unconditional (it takes no arguments: there is
nothing about a particular machine's `[estop]` block — fault_pin,
out_pin, neither — that changes this binding).
"""

from __future__ import annotations

from services.halcompiler.components.EstopWebguiMapper import EstopWebguiMapper


def test_binds_webgui_estop_straight_into_halui_activate():
    lines = EstopWebguiMapper.to_lines()
    assert "net estop-activate webgui.estop => halui.estop.activate" in lines


def test_output_is_stable_regardless_of_call_site():
    """No parameters — the binding never varies per machine."""
    assert EstopWebguiMapper.to_lines() == EstopWebguiMapper.to_lines()
