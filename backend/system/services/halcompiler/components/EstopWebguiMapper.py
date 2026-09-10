"""The E-stop's UI trigger -> `webgui_connections.hal`.

`StateService.activate_estop()` (`backend/machine/services/
StateService.py`) now generates the pulse itself — assert
``webgui.estop`` True, hold briefly, reset to False — rather than
relying on a HAL-side `oneshot` to turn a held level into an edge
(that turned out not to be as simple as it sounds). `webgui.estop` is
therefore already a clean 0 -> 1 -> 0 edge by the time HAL sees it, so
the binding is a plain passthrough net, exactly like a spindle's
`TargetRpm` or a heater's `target-temperature` — see
`SpindleWebguiMapper`/`HeaterWebguiMapper` for why this lives in
`webgui_connections.hal` rather than `machine.hal`.
"""

from __future__ import annotations


class EstopWebguiMapper:
    """`net` line binding `webgui.estop` onto `halui.estop.activate`."""

    @staticmethod
    def to_lines() -> list[str]:
        return [
            "# Estop",
            "net estop-activate webgui.estop => halui.estop.activate",
            "",
        ]


__all__ = ["EstopWebguiMapper"]
