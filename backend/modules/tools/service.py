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
from dataclasses import dataclass
from typing import Dict, List, Literal, Optional

from fastapi import HTTPException
from hardware import linuxcnc_mock
from hardware.connection import execute_sync_cmd, linuxcnc

from modules.temperature.service import read_temperature
from modules.tools.config_mapper import (
    SpindlePins,
    get_spindle_hal_pin_map,
    load_active_tools,
)

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


@dataclass(slots=True)
class SpindleSettingsDTO:
    """Single entry-point payload for spindle control.

    The state machine in :meth:`ToolsService.set_spindle_speed`
    consumes every field; the legacy ``POST /spindle`` endpoint
    translates its three-action vocabulary (``forward`` /
    ``backward`` / ``stop``) into this DTO before delegating.

    Attributes
    ----------
    speed:
        Target RPM for ``state == "running"``. Ignored for
        ``state == "idle"``. Clamped to ``0..200_000`` by the
        router's Pydantic model.
    override:
        Relative override factor (``0.0``–``2.0``; ``1.0`` =
        100 %). Written to ``halui.spindle.override.scale`` before
        every M-code dispatch. The absolute-override counterpart
        is intentionally not surfaced here.
    direction:
        ``"forward"`` → ``M3 S{speed}``, ``"reverse"`` → ``M4 S{speed}``.
        Ignored when ``state == "idle"``.
    state:
        ``"idle"`` stops the spindle (``M5``); ``"running"`` starts
        it (``M3`` / ``M4`` according to ``direction``). Mid-spin
        direction changes raise :class:`HTTPException` ``409`` —
        the operator must stop first.
    """

    speed:     int
    override:  float = 1.0
    direction: Literal["forward", "reverse"] = "forward"
    state:     Literal["idle", "running"] = "running"


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
    could persist the state alongside the mock's
    ``_machine_state.spindle_actual``; for the UI flow (operator
    presses forward, then reverse) the in-memory tracker is enough.
    """

    def __init__(self) -> None:
        # tool_id -> "idle" | "forward" | "reverse"
        self._spindle_state: Dict[str, str] = {}

    def collect_tools(self) -> List[dict]:
        """Return the active ``hardware.json`` tool list with runtime state."""
        raw = load_active_tools()
        return [_overlay_runtime_state(tool) for tool in raw]

    def get_spindle(self, tool_id: str) -> Dict[str, object]:
        """Return the live state + HAL pin map for ``tool_id``.

        Raises :class:`HTTPException` ``404`` when the active
        ``hardware.json`` declares no digital spindle with that id
        (the operator addressed an unknown machine handle). The
        returned dict carries the canonical :class:`SpindlePins`
        (as a plain dict for JSON-friendliness), the telemetry
        snapshot (``actual`` / ``is_connected`` / ``error_count``),
        and the current service-tracked ``state`` (``"idle"`` /
        ``"forward"`` / ``"reverse"``).
        """
        if not isinstance(tool_id, str) or not tool_id:
            raise HTTPException(
                status_code=400,
                detail="Spindle tool_id must be a non-empty string",
            )

        pins_map = get_spindle_hal_pin_map()
        pins = pins_map.get(tool_id)
        if pins is None:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown digital spindle: {tool_id!r}",
            )

        telemetry = read_spindle_telemetry(tool_id) or {
            "actual": 0,
            "is_connected": False,
            "error_count": 0,
        }
        return {
            "id": tool_id,
            "pins": {
                "id":          pins.id,
                "at_speed":    pins.at_speed,
                "forward":     pins.forward,
                "reverse":     pins.reverse,
                "on":          pins.on,
                "pwm":         pins.pwm,
                "rpm_out":     pins.rpm_out,
                "istop":       pins.istop,
                "estop":       pins.estop,
                "vfd_enable":  pins.vfd_enable,
            },
            "state": self._spindle_state.get(tool_id, "idle"),
            **telemetry,
        }

    def set_spindle_speed(
        self,
        pins: SpindlePins,
        dto: SpindleSettingsDTO,
    ) -> str:
        """Single spindle dispatch entry point.

        Consumes a :class:`SpindleSettingsDTO` and applies the
        state machine:

        * ``state == "idle"`` → ``M5``, transition to idle.
        * ``state == "running"`` and current == idle → ``M3`` /
          ``M4`` per ``direction``, transition to that direction.
        * ``state == "running"`` and current == same direction →
          ``M3`` / ``M4`` with the new speed (RPM update).
        * ``state == "running"`` and current == opposite direction →
          :class:`HTTPException` ``409`` — operator must stop first.

        The override is written to ``halui.spindle.override.scale``
        before every M-code dispatch when it differs from the
        LinuxCNC default of ``1.0``. Returns the exact MDI string
        dispatched so the router can echo it back to the caller.
        """
        if not isinstance(dto, SpindleSettingsDTO):
            raise HTTPException(
                status_code=400,
                detail="Spindle settings must be a SpindleSettingsDTO",
            )
        if not isinstance(pins, SpindlePins):
            raise HTTPException(
                status_code=400,
                detail="Spindle pins must be a SpindlePins record",
            )

        current = self._spindle_state.get(pins.id, "idle")

        # State-machine guard — reject mid-spin direction reversal.
        if (
            dto.state == "running"
            and current != "idle"
            and dto.direction != current
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Spindle {pins.id!r} is already spinning {current}; "
                    "stop it before reversing."
                ),
            )

        self._ensure_mdi_mode()

        # Always write the override first so the next M-code runs at
        # the requested scale. Skipping the MDI when override is the
        # LinuxCNC default (1.0) keeps the output clean for the
        # common case.
        if dto.override != 1.0:
            self._dispatch_setp(DEFAULT_SPINDLE_OVERRIDE_PIN, dto.override)

        if dto.state == "idle":
            mdi = M5_STOP
            new_state = "idle"
        else:
            template = (
                M3_FORWARD if dto.direction == "forward" else M4_BACKWARD
            )
            mdi = template.format(speed=dto.speed)
            new_state = dto.direction

        self._dispatch_mdi(mdi)
        self._spindle_state[pins.id] = new_state
        return mdi

    def set_spindle_override_relative(
        self,
        pins: SpindlePins,
        value: float,
    ) -> None:
        """Write the relative spindle override only — no state change.

        Thin wrapper around :func:`_dispatch_setp` for the canonical
        ``halui.spindle.override.scale`` pin. The service intentionally
        does not provide an absolute counterpart — the operator-facing
        surface only writes the relative knob. ``value`` is forwarded
        verbatim; callers are expected to have clamped it to
        ``[0.0, 2.0]`` (LinuxCNC's documented range).
        """
        self._dispatch_setp(DEFAULT_SPINDLE_OVERRIDE_PIN, float(value))

    def control_spindle(
        self,
        tool_id: str,
        action: str,
        speed: int,
        override: float = 1.0,
    ) -> str:
        """Dispatch a spindle command (legacy ``POST /spindle`` adapter).

        ``action`` must be one of ``"forward"`` / ``"backward"`` /
        ``"stop"``; the call returns the exact MDI string dispatched
        so the router can echo it back to the caller. Internally
        builds a :class:`SpindleSettingsDTO` and delegates to
        :meth:`set_spindle_speed`, which owns the state machine.

        ``override`` (default ``1.0``) is the relative override
        factor applied via ``halui.spindle.override.scale``. The
        legacy endpoint previously never wrote the pin, so the
        default of ``1.0`` preserves the historical behaviour.
        """
        if not isinstance(tool_id, str) or not tool_id:
            raise HTTPException(
                status_code=400,
                detail="Spindle tool_id must be a non-empty string",
            )
        if action not in {"forward", "backward", "stop"}:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Invalid spindle action: {action!r}; expected "
                    "'forward', 'backward', or 'stop'."
                ),
            )

        pins_map = get_spindle_hal_pin_map()
        pins = pins_map.get(tool_id)
        if pins is None:
            # Back-compat fallback: the legacy ``POST /spindle``
            # route historically accepted any ``tool_id`` without
            # validating it against ``hardware.json``. Preserve that
            # behaviour by dispatching the M-code with an empty
            # :class:`SpindlePins` record so callers without a
            # compiled profile (tests, dev fixtures) keep working.
            # The stricter lookup still lives in :meth:`get_spindle`
            # and :meth:`set_spindle_speed` — those raise ``404``
            # for unknown ids and are the preferred entry points.
            pins = SpindlePins(id=tool_id)

        if action == "stop":
            dto = SpindleSettingsDTO(
                speed=0,
                override=override,
                direction="forward",
                state="idle",
            )
        else:
            dto = SpindleSettingsDTO(
                speed=speed,
                override=override,
                direction=action,  # "forward" / "backward"
                state="running",
            )
        return self.set_spindle_speed(pins, dto)

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