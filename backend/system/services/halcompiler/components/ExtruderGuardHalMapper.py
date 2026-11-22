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

**Flow** (``M221``, the UI's flow %): on a Remora board the extruder
joint's position command and feedback go through the component, which
scales the extruder's moves by ``flow-percent`` (``webgui.flow``) —
rebased on every change, so a new factor never jumps the position:

    net j<n>pos-cmd joint.<n>.motor-pos-cmd => extruder-<id>.pos-cmd-in
    net j<n>pos-cmd-flow extruder-<id>.pos-cmd-out => remora.joint.<n>.pos-cmd
    net j<n>pos-fb remora.joint.<n>.pos-fb => extruder-<id>.pos-fb-in
    net j<n>pos-fb-flow extruder-<id>.pos-fb-out => joint.<n>.motor-pos-fb

`halui.abort` stops the program / MDI move, as Klipper refuses an
"extrude below minimum temp"; the component prints the error. The motor
enable is not gated: a disabled stepper would let LinuxCNC's commanded
position run away from the real one. An extruder without a sensor or
without a motion joint gets no guard.
"""
from __future__ import annotations

from typing import Iterable, Optional

from models.machineconfig.HardwareJsonModels import Stepper, Tool
from models.machineconfig.HalFragmentModels import SERVO_THREAD, Addf, HalFragment

#: Klipper's default ``min_extrude_temp`` (°C).
DEFAULT_MIN_EXTRUDE_TEMP = 170.0


class ExtruderGuardHalMapper:
    @staticmethod
    def component(tool_id: str) -> str:
        """The tool's ``extruder`` component instance."""
        return f"extruder-{tool_id}"

    @staticmethod
    def guarded_joint(tool: Tool, joints: Iterable[Stepper]) -> Optional[int]:
        """The extruder ``tool``'s joint number when it gets a guard (a sensor
        and a motion joint), else ``None``."""
        if tool.type != "extruder" or not tool.sensor:
            return None
        return next((j.joint_number for j in joints if j.id == tool.id), None)

    @staticmethod
    def to_fragment(tool: Tool, joint_number: int, flow: bool = False) -> HalFragment:
        """``flow``: route the joint's position through the component
        (Remora: `RemoraStepperHalMapper` leaves those nets out)."""
        tool_id = tool.id
        comp = ExtruderGuardHalMapper.component(tool_id)
        min_temp = DEFAULT_MIN_EXTRUDE_TEMP if tool.min_extrude_temp is None else tool.min_extrude_temp
        fragment = HalFragment()
        fragment.loadrt.append(f"loadrt extruder names={comp}")
        # after motion (order 1): reads this period's vel-cmd
        fragment.addf.append(Addf(comp, SERVO_THREAD, order=2))
        fragment.setp.append(f"setp {comp}.min-extrude-temp {min_temp:g}")
        if tool.pressure_advance_smooth_time is not None:
            fragment.setp.append(f"setp {comp}.pa-smooth-time {tool.pressure_advance_smooth_time:g}")
        fragment.nets.append(f"net {tool.sensor}-PV => {comp}.current-temp")
        fragment.nets.append(f"net {tool_id}-vel-cmd joint.{joint_number}.vel-cmd => {comp}.vel-cmd")
        # homing sets the position in place: no guard meanwhile
        fragment.nets.append(f"net {tool_id}-homing joint.{joint_number}.homing => {comp}.homing")
        if flow:
            n = joint_number
            fragment.nets.extend([
                f"net j{n}pos-cmd joint.{n}.motor-pos-cmd => {comp}.pos-cmd-in",
                f"net j{n}pos-cmd-flow {comp}.pos-cmd-out => remora.joint.{n}.pos-cmd",
                f"net j{n}pos-fb remora.joint.{n}.pos-fb => {comp}.pos-fb-in",
                f"net j{n}pos-fb-flow {comp}.pos-fb-out => joint.{n}.motor-pos-fb",
            ])
        return fragment


__all__ = ["DEFAULT_MIN_EXTRUDE_TEMP", "ExtruderGuardHalMapper"]
