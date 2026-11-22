"""``[input_pin NAME]`` -> `webgui_connections.hal`: the reading onto
``webgui.<id>`` and the halui MDI edges (the realtime half is
`InputPinHalMapper`)."""
from __future__ import annotations

from models.machineconfig.HardwareJsonModels import InputPin
from models.machineconfig.InputPinActionModels import MdiCommand


class InputPinWebguiMapper:
    @staticmethod
    def to_lines(input_pin: InputPin, commands: list[MdiCommand]) -> list[str]:
        pin_id = input_pin.id
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


__all__ = ["InputPinWebguiMapper"]
