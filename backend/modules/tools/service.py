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
    mark_spindle_connected,
    read_hal_pin,
)

from modules.temperature.service import collect_sensors
from modules.tools.config_mapper import (
    SpindleDigitalPins,
    get_spindle_hal_pin_map,
    get_spindle_hal_pin_maps,
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
    translates its vocabulary into this DTO before delegating.

    Attributes
    ----------
    speed:
        Target RPM when ``state`` is ``"forward"`` or ``"reverse"``.
        Ignored when ``state == "stop"`` or if ``master_override_enable``
        is ``True``. Clamped to ``0..200_000`` by the router's Pydantic model.
    master_override:
        Absolute target RPM used exclusively when ``master_override_enable``
        is ``True``.
    override:
        Relative override factor (``0.0``–``2.0``; ``1.0`` = 100%).
        Written to ``halui.spindle.override.scale`` before every M-code
        dispatch. Ignored if ``master_override_enable`` is ``True``.
    master_override_enable:
        If enabled, bypasses standard ``speed`` and ``override`` scaling
        and directly forces the spindle to the ``master_override`` RPM.
    state:
        The commanded spindle action. ``"stop"`` halts the spindle (``M5``);
        ``"forward"`` starts it clockwise (``M3``); and ``"reverse"`` starts
        it counter-clockwise (``M4``). Mid-spin direction changes raise
        :class:`HTTPException` ``409`` — the operator must stop first.
    """

    speed: int
    master_override: int
    override: float = 1.0
    master_override_enable: bool = False
    state: Literal["forward", "reverse", "stop"] = "forward"



def read_spindle_telemetry(tool_id: str) -> Optional[Dict[str, object]]:
    """Return ``{actual_rpm, is_connected, error_count, ...}`` by reading HAL pins.

    Looks up the canonical ``SpindleDigitalPins`` record for ``tool_id``
    and reads every wired HAL pin via :func:`read_hal_pin`. Each
    value is coerced to its domain type (``int`` for the RPM fields,
    ``bool`` for the alarm / engagement flags) so the response
    consumer sees a fully-populated dict the Pydantic wire model
    can validate without a None fallback path.

    ``is_connected`` and ``error_count`` are eagerly updated by
    :func:`mark_spindle_connected` and the VFD alarm code into the
    mock's ``_machine_state.spindle_actual`` dict — in the mock
    path those writes hit the dict before the HAL subscription
    callback fires, so reading them from the HAL pin alone would
    show ``None`` for the first tick. When ``USE_MOCK`` is true,
    the function therefore consults the mock dict first and falls
    back to the HAL pin for the RPM / alarm fields.

    When the spindle is absent from the active ``hardware.json``
    (no ``SpindleDigitalPins`` to bind to), the function still
    returns a fully-populated dict with zero defaults so the
    consumer's ``reading["actual_rpm"] if reading else 0`` branch
    keeps working without a separate None check.
    """
    if not isinstance(tool_id, str) or not tool_id:
        raise HTTPException(
            status_code=400,
            detail="Spindle tool_id must be a non-empty string"
        )

    pins = get_spindle_hal_pin_map(tool_id)

    def _as_int(value):
        return int(value) if value is not None else 0

    def _as_bool(value):
        return bool(value) if value is not None else False

    if pins is None:
        return {
            "last_error":      False,
            "error_count":     0,
            "is_connected":    False,
            "spindle_at_speed": False,
            "target_rpm":      0,
            "actual_rpm":      0,
        }

    # Mock-specific eagerly-updated fields. Import locally so the
    # function stays importable on real-hardware deployments where
    # ``linuxcnc_mock`` is not on the import path.
    mock_connected = None
    mock_error_count = None
    from hardware.connection import USE_MOCK
    if USE_MOCK:
        try:
            from hardware import linuxcnc_mock
            with linuxcnc_mock._machine_state.lock:
                entry = linuxcnc_mock._machine_state.spindle_actual.get(tool_id)
            if entry:
                mock_connected = entry.get("is_connected")
                mock_error_count = entry.get("error_count")
        except Exception:  # noqa: BLE001 — mock import / attribute may be absent
            pass

    return {
        "last_error":      _as_bool(read_hal_pin(pins.last_error)),
        "error_count":     mock_error_count if mock_error_count is not None
                           else _as_int(read_hal_pin(pins.error_count)),
        "is_connected":    bool(mock_connected) if mock_connected is not None
                           else _as_bool(read_hal_pin(pins.is_connected)),
        "spindle_at_speed": _as_bool(read_hal_pin(pins.spindle_at_speed)),
        "target_rpm":      _as_int(read_hal_pin(pins.target_rpm)),
        "actual_rpm":      _as_int(read_hal_pin(pins.actual_rpm)),
    }


def _overlay_runtime_state(tool: dict, sensors: Dict[str, Dict[str, float]]) -> dict:
    out = dict(tool)
    if tool.get("type") in _HEATING_TOOL_TYPES:
        out = _heater_state(tool , sensors)
    elif tool.get("type") == "spindle_digital":
        out = _digital_spindle_state(tool , sensors)
    return out

def _heater_state(tool: dict, sensors: Dict[str, Dict[str, float]]):
    out = dict(tool)
    sensor_id = tool.get("sensor")
    reading = sensors.get(sensor_id) if sensor_id else None
    if reading:
        out["actual"] = reading.get("actual", 0.0)
        out["target"] = reading.get("target", 0.0)
    else:
        out["actual"] = 0.0
        out["target"] = 0.0
    return out

def _digital_spindle_state(tool: dict, sensors: Dict[str, Dict[str, float]]):
    out = dict(tool)
    tool_id = tool.get("id")
    reading = read_spindle_telemetry(tool_id) if tool_id else None
    out["actual_rpm"] = reading["actual_rpm"] if reading else 0
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
    could persist the state alongside the spindle telemetry buffer;
    for the UI flow (operator presses forward, then reverse) the
    in-memory tracker is enough.
    """

    def __init__(self) -> None:
        # tool_id -> "idle" | "forward" | "reverse"
        self._spindle_state: Dict[str, str] = {}

    def collect_tools(self) -> List[dict]:
        """Return the active ``hardware.json`` tool list with runtime state."""
        raw = load_active_tools()
        sensors = collect_sensors()
        return [_overlay_runtime_state(tool, sensors) for tool in raw]

    def get_spindle(self, tool_id: str) -> Dict[str, object]:

        if not isinstance(tool_id, str) or not tool_id:
            raise HTTPException(status_code=400, detail="Spindle tool_id must be a non-empty string",)

        pins = get_spindle_hal_pin_map(tool_id)

        if pins is None:
            raise HTTPException(status_code=404, detail=f"Unknown digital spindle: {tool_id!r}",)

        telemetry = read_spindle_telemetry(tool_id)

        return {
            "id": tool_id,
            "pins": {
                "id":              pins.id,
                "spindle_at_speed": pins.spindle_at_speed,
                "target_rpm":      pins.target_rpm,
                "actual_rpm":      pins.actual_rpm,
                "is_connected":    pins.is_connected,
                "error_count":     pins.error_count,
                "last_error":      pins.last_error,
            },
            "state": self._spindle_state.get(tool_id, "idle"),
            "actual": telemetry["actual_rpm"],
            "is_connected": telemetry["is_connected"],
            "error_count": telemetry["error_count"],
        }

    def set_spindle_speed(
        self,
        pins: SpindleDigitalPins,
        dto: SpindleSettingsDTO,
    ) -> str:
        """Single spindle dispatch entry point.

        Consumes a :class:`SpindleSettingsDTO` and applies the
        state machine:

        * ``state == "stop"`` → ``M5``, transition to idle.
        * ``state == "forward"`` / ``"reverse"`` and current == idle
          → ``M3`` / ``M4`` per ``state``, transition to that direction.
        * ``state == "forward"`` / ``"reverse"`` and current == same
          direction → ``M3`` / ``M4`` with the new target RPM
          (``speed`` or ``master_override`` depending on the bypass).
        * ``state == "forward"`` / ``"reverse"`` and current ==
          opposite direction → :class:`HTTPException` ``409`` —
          operator must stop first.

        ``master_override_enable`` bypasses the standard ``speed`` /
        ``override`` path: the dispatch uses ``master_override`` RPM
        directly and the ``halui.spindle.override.scale`` pin is
        left untouched. The override pin is otherwise written before
        every M-code dispatch when it differs from the LinuxCNC
        default of ``1.0``. Returns the exact MDI string dispatched
        so the router can echo it back to the caller.
        """
        if not isinstance(dto, SpindleSettingsDTO):
            raise HTTPException(
                status_code=400,
                detail="Spindle settings must be a SpindleSettingsDTO",
            )
        if not isinstance(pins, SpindleDigitalPins):
            raise HTTPException(
                status_code=400,
                detail="Spindle pins must be a SpindleDigitalPins record",
            )

        current = self._spindle_state.get(pins.id, "idle")

        # State-machine guard — reject mid-spin direction reversal.
        if (
            dto.state != "stop"
            and current != "idle"
            and dto.state != current
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
        # common case. ``master_override_enable`` bypasses the whole
        # override path — the caller is forcing an absolute RPM and
        # does not want the relative knob applied.
        if dto.master_override_enable:
            pass
        elif dto.override != 1.0:
            self._dispatch_setp(DEFAULT_SPINDLE_OVERRIDE_PIN, dto.override)

        if dto.state == "stop":
            mdi = M5_STOP
            new_state = "idle"
            new_target = 0
        else:
            target_rpm = (
                dto.master_override if dto.master_override_enable else dto.speed
            )
            template = M3_FORWARD if dto.state == "forward" else M4_BACKWARD
            mdi = template.format(speed=target_rpm)
            new_state = dto.state
            new_target = target_rpm

        self._dispatch_mdi(mdi)
        self._spindle_state[pins.id] = new_state

        # Push the new target RPM into the mock-mode simulator so
        # ``hardware.spindle_pin_simulator.read_spindle_pin`` ramps
        # the spindle toward ``new_target`` RPM on every poll tick.
        # On real hardware the HAL subscription manager reads the
        # real ``rpm_out`` pin instead; this call is a no-op in that
        # path because the simulator is only consulted when
        # ``USE_MOCK`` is true.
        try:
            from hardware.spindle_pin_simulator import (
                set_spindle_target,
            )
            set_spindle_target(pins.id, new_target)
        except Exception:  # noqa: BLE001 - simulator missing on real hw
            pass

        # Eagerly update the spindle's ``is_connected`` flag so the
        # dashboard's SpindleCard reflects the operator's action
        # before the HAL poll loop has a chance to fire. The
        # simulator's per-tick poll refines ``actual`` (the ramp) on
        # the next iteration; ``is_connected`` flips immediately so
        # the operator's command reflects in the UI within the
        # next snapshot tick (~1 s). Routed through the unified
        # :func:`hardware.connection.mark_spindle_connected` so the
        # mock-only state write stays inside the mock.
        mark_spindle_connected(
            pins.id, dto.state != "stop",
        )

        return mdi

    def set_spindle_override_relative(
        self,
        pins: SpindleDigitalPins,
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
        master_override: int = 0,
        master_override_enable: bool = False,
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

        ``master_override`` is the absolute RPM applied when
        ``master_override_enable`` is true (default ``False``).
        When the bypass is on, ``speed`` and ``override`` are
        ignored and the dispatch uses ``master_override`` directly.
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

        pins_map = get_spindle_hal_pin_maps()
        pins = pins_map.get(tool_id)
        if pins is None:
            # Back-compat fallback: the legacy ``POST /spindle``
            # route historically accepted any ``tool_id`` without
            # validating it against ``hardware.json``. Preserve that
            # behaviour by dispatching the M-code with an empty
            # :class:`SpindleDigitalPins` record so callers without a
            # compiled profile (tests, dev fixtures) keep working.
            # The stricter lookup still lives in :meth:`get_spindle`
            # and :meth:`set_spindle_speed` — those raise ``404``
            # for unknown ids and are the preferred entry points.
            pins = SpindleDigitalPins(id=tool_id)

        if action == "stop":
            dto = SpindleSettingsDTO(
                speed=0,
                master_override=master_override,
                override=override,
                master_override_enable=master_override_enable,
                state="stop",
            )
        else:
            dto = SpindleSettingsDTO(
                speed=speed,
                master_override=master_override,
                override=override,
                master_override_enable=master_override_enable,
                state="forward" if action == "forward" else "reverse",
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