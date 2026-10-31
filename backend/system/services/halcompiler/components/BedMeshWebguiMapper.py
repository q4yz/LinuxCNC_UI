"""`[bed_mesh]` -> `webgui_connections.hal`: the compensation component's
inputs that only exist once `webgui` / `halui` run
(`.agent/component/bed_mesh.md`; the realtime half is `BedMeshHalMapper`).

`webgui.bed-mesh-enable` is the UI's on/off switch
(`BedMeshService` in the machine backend).
"""

from __future__ import annotations


class BedMeshWebguiMapper:
    @staticmethod
    def to_lines() -> list[str]:
        return [
            "# Bed mesh Z compensation (Remora compensation component)",
            "net bed-mesh-enable webgui.bed-mesh-enable => compensation.enable-in",
            "net bed-mesh-x halui.axis.x.pos-relative => compensation.x-pos",
            "net bed-mesh-y halui.axis.y.pos-relative => compensation.y-pos",
            "net bed-mesh-z halui.axis.z.pos-relative => compensation.z-pos",
            "",
        ]


__all__ = ["BedMeshWebguiMapper"]
