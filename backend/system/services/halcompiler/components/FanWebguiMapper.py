"""A `kind: "part"` fan's UI trigger -> `webgui_connections.hal`.

Plain passthrough, same shape as `HeaterWebguiMapper`'s own fan
binding — the operator/G-code writes `webgui.<id>`, the physical pin
is bound elsewhere (`FanHalMapper`). A `kind: "heater"` fan gets no
binding at all: `.agent/component/fan.md` — the HAL manages it, the
operator never does.
"""

from __future__ import annotations

from typing import Any


class FanWebguiMapper:
    """`net` line binding one `kind: "part"` fan onto `webgui.<id>`."""

    @staticmethod
    def to_lines(fan: dict[str, Any]) -> list[str]:
        fan_id = str(fan["id"])
        return [
            f"# Fan: {fan_id}",
            f"net {fan_id}-SP <= webgui.{fan_id}",
            "",
        ]


__all__ = ["FanWebguiMapper"]
