"""An extruder's cold-extrusion guard -> ``webgui_connections.hal``: the
abort onto halui, the flow % and pressure advance from the machine backend."""
from __future__ import annotations

from typing import Any

from .ExtruderGuardHalMapper import ExtruderGuardHalMapper


class ExtruderGuardWebguiMapper:
    @staticmethod
    def to_lines(tool: dict[str, Any]) -> list[str]:
        tool_id = str(tool["id"])
        comp = ExtruderGuardHalMapper.component(tool_id)
        return [
            f"# Cold-extrusion guard: {tool_id} (machine.hal's extruder-{tool_id})",
            f"net {tool_id}-cold-extrude {comp}.cold-extrude => halui.abort",
            # the flow % (M221, the UI) — scales the moves on a Remora board
            f"net {tool_id}-flow webgui.flow => {comp}.flow-percent",
            # pressure advance (the profile's value, SET_PRESSURE_ADVANCE, M900)
            f"net {tool_id}-pressure-advance webgui.pressure-advance => {comp}.pressure-advance",
            "",
        ]


__all__ = ["ExtruderGuardWebguiMapper"]
