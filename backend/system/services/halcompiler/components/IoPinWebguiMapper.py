"""``[output_pin NAME]`` / ``[input_pin NAME]`` -> `webgui_connections.hal`:
the UI side and the halui MDI edges (`.agent/component/io_pins.md`; the
realtime half is `IoPinHalMapper`). ``IoService`` (machine backend)
owns the ``webgui.<id>`` pins.
"""

from __future__ import annotations

from typing import Any

from .IoPinHalMapper import MdiCommand


class IoPinWebguiMapper:
    @staticmethod
    def output_lines(output_pin: dict[str, Any], latched: bool = False) -> list[str]:
        """``latched``: inputs set this output too — the UI is one more
        event into its latch (value + a toggled ``-set``) and reads the
        result back from ``webgui.<id>-state``."""
        pin_id = str(output_pin["id"])
        if latched:
            return [
                f"# Output pin: {pin_id} (latched: the UI and input edges set it)",
                f"net {pin_id}-ui-value webgui.{pin_id} => {pin_id}-set0.in1",
                f"net {pin_id}-ui-set webgui.{pin_id}-set => {pin_id}-ui-edge.in",
                f"net {pin_id}-latched => webgui.{pin_id}-state",
                "",
            ]
        if output_pin.get("pwm"):
            return [f"# Output pin: {pin_id} (PWM)", f"net {pin_id}-value webgui.{pin_id} => {pin_id}-scale.in", ""]
        return [f"# Output pin: {pin_id}", f"net {pin_id}-out <= webgui.{pin_id}", ""]

    @staticmethod
    def input_lines(input_pin: dict[str, Any], commands: list[MdiCommand]) -> list[str]:
        pin_id = str(input_pin["id"])
        lines = [f"# Input pin: {pin_id}", f"net {pin_id}-in => webgui.{pin_id}"]
        for command in commands:
            if command.input_id != pin_id:
                continue
            halui = f"halui.mdi-command-{command.index:02d}"
            if command.edge == "rising":
                lines.append(f"net {pin_id}-in => {halui}")
            else:
                lines.append(f"net {pin_id}-released {pin_id}-released.out => {halui}")
        return [*lines, ""]


__all__ = ["IoPinWebguiMapper"]
