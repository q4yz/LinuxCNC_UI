"""An extruder's cold-extrusion guard (Klipper's ``min_extrude_temp``,
`.agent/component/exturder.md` § 3) -> the Remora `extruder` component.

`extruder` (Remora-m8p `LinuxCNC/Components/Extruder/extruder.comp`,
installed by `scripts/install_hal_components.sh`) raises `cold-extrude`
while the extruder joint is commanded to move (`joint.N.vel-cmd`, extrude
or retract) and the hotend reads below `min-extrude-temp`:

    machine.hal:
    loadrt extruder names=extruder-<id>
    addf extruder-<id> servo-thread
    setp extruder-<id>.min-extrude-temp <min_extrude_temp || 170>
    net <sensor>-PV => extruder-<id>.current-temp
    net <id>-vel-cmd joint.<n>.vel-cmd => extruder-<id>.vel-cmd
    net <id>-homing joint.<n>.homing => extruder-<id>.homing

    webgui_connections.hal (halui pins exist only there):
    net <id>-cold-extrude extruder-<id>.cold-extrude => halui.abort

Homing sets the extruder's position in place, a one-period `vel-cmd`
spike: the component ignores the joint while it homes and only stops a
move that lasted `min-extrude-time` (50 ms).

`halui.abort` stops the program / MDI move, as Klipper refuses an
"extrude below minimum temp"; the component prints the error. The motor
enable is not gated: a disabled stepper would let LinuxCNC's commanded
position run away from the real one. An extruder without a sensor or
without a motion joint gets no guard.
"""
from __future__ import annotations

from typing import Any, Optional

from models.machineconfig.HalFragmentModels import SERVO_THREAD, Addf, HalFragment

#: Klipper's default ``min_extrude_temp`` (°C).
DEFAULT_MIN_EXTRUDE_TEMP = 170.0


def _component(tool_id: str) -> str:
    return f"extruder-{tool_id}"


def guarded_joint(payload: dict[str, Any], tool: dict[str, Any]) -> Optional[int]:
    """The extruder ``tool``'s joint number when it gets a guard (a sensor
    and a motion joint), else ``None``."""
    if tool.get("type") != "extruder" or not tool.get("sensor"):
        return None
    for joint in payload.get("joints") or []:
        if isinstance(joint, dict) and joint.get("id") == tool.get("id") and joint.get("joint_number") is not None:
            return int(joint["joint_number"])
    return None


class ExtruderGuardHalMapper:
    @staticmethod
    def to_fragment(tool: dict[str, Any], joint_number: int) -> HalFragment:
        tool_id = str(tool["id"])
        comp = _component(tool_id)
        min_temp = tool.get("min_extrude_temp")
        min_temp = DEFAULT_MIN_EXTRUDE_TEMP if min_temp is None else float(min_temp)
        fragment = HalFragment()
        fragment.loadrt.append(f"loadrt extruder names={comp}")
        # after motion (order 1): reads this period's vel-cmd
        fragment.addf.append(Addf(comp, SERVO_THREAD, order=2))
        fragment.setp.append(f"setp {comp}.min-extrude-temp {min_temp:g}")
        fragment.nets.append(f"net {tool['sensor']}-PV => {comp}.current-temp")
        fragment.nets.append(f"net {tool_id}-vel-cmd joint.{joint_number}.vel-cmd => {comp}.vel-cmd")
        # homing sets the position in place: no guard meanwhile
        fragment.nets.append(f"net {tool_id}-homing joint.{joint_number}.homing => {comp}.homing")
        return fragment

    @staticmethod
    def webgui_lines(tool: dict[str, Any]) -> list[str]:
        tool_id = str(tool["id"])
        return [
            f"# Cold-extrusion guard: {tool_id} (machine.hal's extruder-{tool_id})",
            f"net {tool_id}-cold-extrude {_component(tool_id)}.cold-extrude => halui.abort",
            "",
        ]


__all__ = ["DEFAULT_MIN_EXTRUDE_TEMP", "ExtruderGuardHalMapper", "guarded_joint"]
