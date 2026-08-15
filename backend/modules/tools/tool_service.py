"""Tools module service — :class:`ToolsService` (tool telemetry facade).

This is the canonical home for the operator-facing tool list with
runtime state overlaid, and the hardware-dispatch helpers used by
the tools router (``POST /spindle``, ``POST /extruder``,
``POST /tools/{id}/target``). The helper used to live as
module-level functions in ``backend.services.machine_service``; the
base-thread snapshot router (``routers/base_thread.py``) now imports
:func:`get_tools_service` (or ``collect_tools`` directly) from this
module.

Heating-tool telemetry (extruder / heated_bed) is decorated with the
runtime ``actual`` / ``target`` reading via
:func:`modules.temperature.service.collect_sensors`. Digital-spindle
telemetry is read through the unified
:func:`hardware.connection.read_spindle_telemetry` helper, which
routes to either the live LinuxCNC stat channel or the mock
without the service knowing which is active.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Literal, Optional

from fastapi import HTTPException
from hardware.connection import (
    execute_sync_cmd,
    linuxcnc,
)

from modules.temperature.service import collect_sensors
from modules.tools.config_mapper import (
    SpindleDigitalPins,
    get_spindle_hal_pin_map,
    get_spindle_hal_pin_maps,
    get_tools,
)
from modules.tools.dtos.digital_spindle_dto import SpindleStateDTO, SpindleSettingsDTO
from modules.tools.tool_halpin_factory import ToolHalPinFactory

logger = logging.getLogger("backend.modules.tools.service")


# Tools that surface runtime heat state (``actual`` / ``target``)
# read from the mock's ``temperatures`` dict. Spindle / laser tools
# are absent from that dict.
_HEATING_TOOL_TYPES = frozenset({"extruder", "heated_bed"})


# Canonical LinuxCNC MDI strings. Kept module-private so the service
# functions stay readable. The constants are exported through
# :data:`__all__` for unit tests that want to assert the exact
# strings the endpoint emits.
M3_FORWARD = "M3 S{speed}"
M4_BACKWARD = "M4 S{speed}"
M5_STOP = "M5"
G91_RELATIVE = "G91"
G90_ABSOLUTE = "G90"
G1_EXTRUDE = "G1 E{dist} F{speed}"


# Canonical LinuxCNC HAL pin for the relative spindle-override.
# ``halui.spindle.override.scale`` accepts values in the
# ``[0.0, 2.0]`` range — ``1.0`` is the operator-default 100%.
# The absolute-override counterpart is intentionally not exposed
# in this service; the operator-facing surface only writes the
# relative knob.
DEFAULT_SPINDLE_OVERRIDE_PIN = "halui.spindle.override.scale"

def read_spindle_telemetry(tool_id: str) -> SpindleStateDTO:

    if not isinstance(tool_id, str) or not tool_id:
        raise HTTPException(
            status_code=400,
            detail="Spindle tool_id must be a non-empty string"
        )

    try:
        pins = get_spindle_hal_pin_map(tool_id)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=f"Spindle tool '{tool_id}' not found in hardware configuration."
        )

    return pins.to_spindle_state_dto()

#
# def _overlay_runtime_state(tool: dict, sensors: Dict[str, Dict[str, float]]) -> dict:
#     out = dict(tool)
#     if tool.get("type") in _HEATING_TOOL_TYPES:
#         out = _heater_state(tool , sensors)
#     elif tool.get("type") == "spindle_digital":
#         out = _digital_spindle_state(tool , sensors)
#     return out
#
# def _heater_state(tool: dict, sensors: Dict[str, Dict[str, float]]):
#     out = dict(tool)
#     sensor_id = tool.get("sensor")
#     reading = sensors.get(sensor_id) if sensor_id else None
#     if reading:
#         out["actual"] = reading.get("actual", 0.0)
#         out["target"] = reading.get("target", 0.0)
#     else:
#         out["actual"] = 0.0
#         out["target"] = 0.0
#     return out
#



class ToolsService:
    """Operator-facing tool-list facade + dispatch helpers.

    Three responsibilities live here:

    * **Telemetry:** :meth:`collect_tools` loads the active
      ``hardware.json`` ``tools[]`` list and overlays the runtime
      state (heat / spindle telemetry) so the dashboard can render
      a single "live" tool panel.
    * **Spindle dispatch:** :meth:`set_spindle_speed` is the single
      state-machine entry point that consumes a
      :class:`SpindleSettingsDTO`. Forward / reverse / stop actions
      from the legacy ``POST /spindle`` route flow through
      :meth:`control_spindle`, which builds a DTO and delegates.
    * **Extruder + heater dispatch:** :meth:`control_extruder` and
      :meth:`set_tool_target` translate the HTTP-edge Pydantic
      command into the canonical LinuxCNC MDI strings
      (``G91``/``G1``/``G90``, ``set_temperature``) and dispatch
      them via :func:`hardware.connection.execute_sync_cmd`.

    Spindle state tracking
    -----------------------
    The service keeps a tiny per-spindle direction map so the
    state machine can reject mid-spin direction reversals
    (``409 Conflict``). The map is in-memory only — it does not
    survive a service restart. A future hardened implementation
    could persist the state alongside the spindle telemetry buffer;
    for the UI flow (operator presses forward, then reverse) the
    in-memory tracker is enough.
    """

    def __init__(self) -> None:
        pass

    def collect_halpin_tools(self) -> List[dict]:
        """Return the active ``hardware.json`` tool list with runtime state."""
        valid_tools = []
        for tool in get_tools():
            pin_map = ToolHalPinFactory.create(tool)
            if pin_map is not None:
                valid_tools.append(pin_map)

        # sensors = collect_sensors()
        return valid_tools

    def collect_tools(self) -> List[dict]:
        """Return the active ``hardware.json`` tool list with runtime state."""

        # sensors = collect_sensors()
        return [ t.to_state_dto() for t in self.collect_halpin_tools()]



    def control_extruder(
        self, tool_id: str, action: str, distance: float, speed: int
    ) -> str:
        """Dispatch an extruder (extrude / retract) command."""
        self._ensure_mdi_mode()
        signed_dist = distance if action == "extrude" else -distance
        self._dispatch_mdi(G91_RELATIVE)
        move = G1_EXTRUDE.format(dist=signed_dist, speed=speed)
        self._dispatch_mdi(move)
        self._dispatch_mdi(G90_ABSOLUTE)
        return move

    def set_tool_target(self, tool_id: str, target: float) -> str:
        """Set the target temperature for the tool's ``sensor``.

        Looks up the active tool's ``sensor`` reference in the
        ``hardware.json`` ``tools[]`` list and dispatches
        ``set_temperature`` against that sensor id. Raises
        :class:`HTTPException` (404 / 400) for the same reasons the
        historical router did — caller-side error translation is
        intentionally kept in the service so the router stays thin.
        """
        if not tool_id or not isinstance(tool_id, str):
            raise HTTPException(
                status_code=400,
                detail="Tool id must be a non-empty string",
            )

        raw_tools = get_tools()
        tool = next((t for t in raw_tools if t.get("id") == tool_id), None)
        if tool is None:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown tool id: {tool_id!r}",
            )
        sensor_id = tool.get("sensor")
        if not isinstance(sensor_id, str) or not sensor_id:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Tool {tool_id!r} has no temperature sensor "
                    "(spindle / laser tools cannot accept a target)"
                ),
            )

        try:
            execute_sync_cmd("set_temperature", 0, sensor_id, target)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001 - defensive
            logger.error(
                "set_temperature(%s, %s) failed: %s",
                sensor_id,
                target,
                exc,
            )
            raise HTTPException(status_code=500, detail=str(exc))

        return sensor_id

    @staticmethod
    def _ensure_mdi_mode() -> None:
        """Switch the task into MDI mode and wait for the change to commit."""
        execute_sync_cmd(
            "mode",
            5,
            getattr(linuxcnc, "MODE_MDI", 3),
        )

    @staticmethod
    def _dispatch_mdi(command: str) -> None:
        """Issue a single MDI command without waiting for completion."""
        logger.info("tools mdi -> %s", command)
        execute_sync_cmd("mdi", 0, command)

    @staticmethod
    def _dispatch_setp(pin: str, value: float) -> None:
        """Write a HAL pin via ``setp <pin> <value>``.

        Used by the spindle-override path and any future per-pin
        HAL writes the service needs. The router delegates here so
        no router is allowed to import ``hardware.*`` directly (the
        "no router imports a hardware file" rule stays enforced).
        """
        logger.info("tools setp -> %s %s", pin, value)
        execute_sync_cmd("setp", 0, pin, value)



_tools_service: Optional[ToolsService] = None


def get_tools_service() -> ToolsService:
    """Lazy module-level singleton (tool telemetry / dispatch facade)."""
    global _tools_service
    if _tools_service is None:
        _tools_service = ToolsService()
    return _tools_service


def collect_tools() -> List[dict]:
    """Module-level convenience wrapper for backward compatibility."""
    return get_tools_service().collect_tools()




__all__ = [
    "DEFAULT_SPINDLE_OVERRIDE_PIN",
    "G1_EXTRUDE",
    "G90_ABSOLUTE",
    "G91_RELATIVE",
    "M3_FORWARD",
    "M4_BACKWARD",
    "M5_STOP",
    "SpindleSettingsDTO",
    "ToolsService",
    "collect_tools",
    "get_tools_service",
    "read_spindle_telemetry",
]