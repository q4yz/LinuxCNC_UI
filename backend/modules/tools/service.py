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
runtime ``actual`` / ``target`` reading via :func:`read_temperature`
in :mod:`modules.temperature.service`. Digital-spindle telemetry is
read from the mock's ``_machine_state.spindle_actual`` dict via
:func:`read_spindle_telemetry`.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from fastapi import HTTPException
from hardware import linuxcnc_mock
from hardware.connection import execute_sync_cmd, linuxcnc

from modules.temperature.service import read_temperature
from modules.tools.config_mapper import load_active_tools

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


def read_spindle_telemetry(tool_id: str) -> Optional[Dict[str, object]]:
    """Return the live spindle telemetry for ``tool_id``.

    Returns ``None`` when no telemetry has arrived yet. The dict
    shape mirrors ``linuxcnc_mock._machine_state.spindle_actual``
    entries — ``actual`` / ``is_connected`` / ``error_count``.
    """
    if not isinstance(tool_id, str) or not tool_id:
        return None
    with linuxcnc_mock._machine_state.lock:  # noqa: SLF001
        reading = linuxcnc_mock._machine_state.spindle_actual.get(tool_id)
    if not reading:
        return None
    return {
        "actual": reading.get("actual", 0),
        "is_connected": reading.get("is_connected", False),
        "error_count": reading.get("error_count", 0),
    }


def _overlay_runtime_state(tool: dict) -> dict:
    """Augment a ``hardware.json`` tool record with runtime telemetry.

    Returns a **shallow copy** of the input so the helper cannot
    accidentally mutate the loader's source list.

    * Heating tools (``extruder`` + ``heated_bed`` with a non-null
      ``sensor``): overlay ``actual`` / ``target`` from
      :func:`read_temperature`. Defaults to ``0.0`` / ``0.0`` when
      the sensor hasn't been seeded yet.
    * ``spindle_digital``: overlay ``actual_rpm``,
      ``is_connected``, and ``error_count`` from
      :func:`read_spindle_telemetry`. Defaults to
      ``0`` / ``False`` / ``0`` when no telemetry has arrived yet.
    * All other tools (``spindle_analog``, ``laser``): pass through
      unchanged.
    """
    out = dict(tool)
    if tool.get("type") in _HEATING_TOOL_TYPES:
        sensor_id = tool.get("sensor")
        reading = read_temperature(sensor_id) if sensor_id else None
        if reading:
            out["actual"] = reading["actual"]
            out["target"] = reading["target"]
        else:
            out["actual"] = 0.0
            out["target"] = 0.0
    elif tool.get("type") == "spindle_digital":
        tool_id = tool.get("id")
        reading = read_spindle_telemetry(tool_id) if tool_id else None
        out["actual_rpm"] = reading["actual"] if reading else 0
        out["is_connected"] = reading["is_connected"] if reading else False
        out["error_count"] = reading["error_count"] if reading else 0
    return out


class ToolsService:
    """Operator-facing tool-list facade + dispatch helpers.

    Two responsibilities live here:

    * **Telemetry:** :meth:`collect_tools` loads the active
      ``hardware.json`` ``tools[]`` list and overlays the runtime
      state (heat / spindle telemetry) so the dashboard can render
      a single "live" tool panel.
    * **Dispatch:** :meth:`control_spindle`, :meth:`control_extruder`,
      and :meth:`set_tool_target` translate the HTTP-edge Pydantic
      command into the canonical LinuxCNC MDI strings
      (``M3``/``M4``/``M5``, ``G91``/``G1``/``G90``,
      ``set_temperature``) and dispatch them via
      :func:`hardware.connection.execute_sync_cmd`.
    """

    def collect_tools(self) -> List[dict]:
        """Return the active ``hardware.json`` tool list with runtime state."""
        raw = load_active_tools()
        return [_overlay_runtime_state(tool) for tool in raw]

    def control_spindle(self, tool_id: str, action: str, speed: int) -> str:
        """Dispatch a spindle command.

        ``action`` must be one of ``"forward"`` / ``"backward"`` /
        ``"stop"``; the call returns the exact MDI string dispatched
        so the router can echo it back to the caller.
        """
        self._ensure_mdi_mode()

        if action == "forward":
            mdi = M3_FORWARD.format(speed=speed)
        elif action == "backward":
            mdi = M4_BACKWARD.format(speed=speed)
        else:  # action == "stop"
            mdi = M5_STOP

        self._dispatch_mdi(mdi)
        return mdi

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

        raw_tools = load_active_tools()
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
    "ToolsService",
    "get_tools_service",
    "collect_tools",
    "read_spindle_telemetry",
    "M3_FORWARD",
    "M4_BACKWARD",
    "M5_STOP",
    "G91_RELATIVE",
    "G90_ABSOLUTE",
    "G1_EXTRUDE",
]