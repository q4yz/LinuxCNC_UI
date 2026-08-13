"""Machine service — Layer 2 facade over the ``hardware/`` folder.

This module is the canonical home for machine-business logic that
used to live in the (now-deleted) ``modules/machine/{adapter,
facade, service}.py`` split. The previous round split
Service / Adapter / Facade responsibility across three sibling
files inside the module — that was the wrong abstraction layer.
The right home is here: the ``hardware/`` package owns the raw
NML dispatch + HAL subscription; ``services/machine_service``
sits above it as a typed facade that API endpoints (current and
future) call.

Two related service classes live here:

  * :class:`MachineService` — the hardware-layer HAL-pin facade
    used by anything that needs to read endstop states or dispatch
    G-code against the linuxcnc command channel. The class body
    here mirrors what used to live in ``hardware/connection.py``'s
    duplicate ``MachineService`` definition (de-duplicated in
    this round).
  * :class:`MachineControlService` — the machine-business facade
    (state / mode / home / MDI). The HTTP edge for these
    operations now lives in :mod:`backend.modules.state.router`
    (state / mode / MDI) and :mod:`backend.modules.axis.router`
    (``/home``); both routers call into the singleton accessor
    :func:`get_machine_control_service` from this module. The
    facade stays whole — only the HTTP routing was split.

Both services share the helpers in :mod:`backend.hardware.connection`
(``execute_gcode``, ``execute_sync_cmd``, ``is_linuxcnc_connected``,
``get_machine_stat``).
"""
from __future__ import annotations

import logging
import time
import warnings
from enum import Enum
from typing import Dict, List, Optional

from hardware.connection import (
    DeviceConfigMapper,
    HalSubscriptionManager,
    execute_gcode,
    execute_sync_cmd,
    get_machine_stat,
    is_linuxcnc_connected,
    linuxcnc,
)

from hardware import connection
from modules.tools.config_mapper import load_active_tools
from pydantic import BaseModel, Field
# Direct leaf-module import — ``services.line_count_cache`` has no
# ``services``-package dependencies, so this resolves cleanly even
# while ``services/__init__.py`` is mid-init. The previous
# ``from services import lookup_line_count`` triggered the circular
# import that broke ``main.py`` boot (see the traceback captured in
# the PR that introduced this comment).
from services.line_count_cache import lookup as lookup_line_count

# ``MachineService`` is defined in this module below; do NOT import
# it from ``hardware.connection`` (which used to re-export it as a
# backward-compat shim) — that creates the
# ``services.machine_service`` ↔ ``hardware.connection`` circular
# import that broke the test_hardware_layers suite.

logger = logging.getLogger("backend.services.machine_service")


# ---------------------------------------------------------------------------
# State facade enum — the clean, operator-facing vocabulary
# ---------------------------------------------------------------------------
#
# This enum is the single source of truth for the operator-facing
# machine state on the backend side. It mirrors
# ``frontend/src/stores/stateFacade.js::SystemState`` so the wire
# format stays in lockstep across the HTTP / WebSocket boundary.
#
# The values are lowercase strings (not the LinuxCNC NML integer
# constants) — that's the entire point of the facade: API consumers
# never see ``task_state == 1`` / ``task_state == 4`` integers and
# never have to import the ``linuxcnc`` module to interpret them.


class MachineState(str, Enum):
    """Operator-facing machine state.

    Mirrors ``frontend/src/stores/stateFacade.js::SystemState``.
    Values are lowercase strings rather than the LinuxCNC NML
    integer constants so the facade never leaks the underlying
    wire protocol. ``str``-mixin keeps the enum JSON-serialisable
    out of the box (``json.dumps(MachineState.IDLE) == '"idle"'``).
    """

    OFFLINE = "offline"
    ESTOP = "estop"
    POWER_OFF = "power_off"
    IDLE = "idle"
    LOADED = "loaded"
    RUNNING = "running"
    PAUSED = "paused"
    FAILURE = "failure"


# ---------------------------------------------------------------------------
# Layer 2: HAL-pin facade (endstop state, G-code dispatch helpers)
# ---------------------------------------------------------------------------


class MachineService:
    """Hardware-layer high-level interface (HAL-pin + endstop).

    Composes the :class:`DeviceConfigMapper` (``.cfg`` → HAL pin
    names) with the :class:`HalSubscriptionManager` (poll → fire
    callbacks) and the ``execute_gcode`` / ``execute_sync_cmd``
    dispatch helpers so API consumers ask "give me the endstop
    state" without knowing how the pins are wired or how the G-code
    is dispatched.

    Future entry points (axis home via G-code, tool-change G-code,
    …) extend this class without touching the FastAPI router or
    the lower layers.
    """

    def __init__(self,mapper: DeviceConfigMapper, hal_sub_mgr: HalSubscriptionManager,) -> None:
        self.mapper = mapper
        self.hal_mgr = hal_sub_mgr



    def get_endstop_state_subscription(self, pin_list: List[str]) -> dict:
        """Snapshot endstop states + fire the G-code position query.

        Reads every HAL pin via the subscription manager's
        :meth:`HalSubscriptionManager.read_pin` (no subscription is
        registered — this is a one-shot snapshot, not a push
        subscription). When LinuxCNC is reachable the routine
        additionally issues ``M114`` (current position report) so
        the consumer can correlate the pin state with the
        reported axis positions.

        The result is a flat dict suitable for ``JSONResponse`` —
        the router is free to wrap or extend it.
        """
        states = {pin: self.hal_mgr.read_pin(pin) for pin in pin_list}

        gcode_res = self.safe_execute_gcode("M114", 2)

        return {
            "pins": pin_list,
            "states": states,
            "gcode_status": gcode_res,
        }

    def get_endstops(self) -> dict:
        """Top-level call: pins via the mapper, then state read.

        Combines the two Layer-1 / Layer-2 responsibilities:
        :class:`DeviceConfigMapper` knows which pins the machine
        exposes; the subscription manager knows how to read them.
        """
        pins = self.mapper.get_endstop_hal_pin_list()
        return self.get_endstop_state_subscription(pins)

    def safe_execute_gcode(self, command: str, timeout: float = 2.0) -> dict:
        """Executes a G-code command only if the machine is online."""
        if not is_linuxcnc_connected():
            return {"status": "offline"}

        return execute_gcode(command, timeout=timeout)


# ---------------------------------------------------------------------------
# Layer 2: Machine-business facade (state / mode / home / MDI)
# ---------------------------------------------------------------------------





class MachineControlService:
    """

    Each method is a thin wrapper over :func:`execute_sync_cmd` /
    :func:`execute_gcode` that translates the operator-facing string
    (e.g. ``"on"`` / ``"off"`` / ``"estop"``) to its NML integer
    constant before dispatching.
    """

    # Operator-facing labels → NML constant attribute on the
    # ``linuxcnc`` module. Centralised so adding a new state is a
    # single-line change.
    _STATE_CODES = {
        "on": "STATE_ON",
        "off": "STATE_OFF",
        "estop": "STATE_ESTOP",
        "estop_reset": "STATE_ESTOP_RESET",
    }
    _MODE_CODES = {
        "manual": "MODE_MANUAL",
        "auto": "MODE_AUTO",
        "mdi": "MODE_MDI",
    }

    @staticmethod
    def _resolve(table: dict, name: str) -> int:
        """Translate an operator-facing name to its NML integer.

        Missing entry → caller bug (``ValueError``); missing
        constant on the linuxcnc module → system misconfiguration
        (``RuntimeError``). Both bubble through ``execute_sync_cmd``'s
        own ``HTTPException(503)`` when the channel is offline.
        """
        attr = table.get(name)
        if attr is None:
            valid = ", ".join(sorted(table))
            raise ValueError(
                f"Unknown machine state / mode: {name!r}. "
                f"Expected one of: {valid}"
            )
        code = getattr(linuxcnc, attr, None)
        if code is None:
            raise RuntimeError(
                f"linuxcnc constant {attr!r} unavailable on this build"
            )
        return code

    def set_state(self, name: str) -> None:
        code = self._resolve(self._STATE_CODES, name)
        execute_sync_cmd("state", 3, code)
        warnings.warn(
            " is deprecated and will be removed "
            "use specific methode instead",
            DeprecationWarning,
            stacklevel=2
        )
        logger.info("dispatched machine state -> %s", name)

    def set_mode(self, name: str) -> None:
        code = self._resolve(self._MODE_CODES, name)
        execute_sync_cmd("mode", 5, code)
        logger.info("dispatched machine mode -> %s", name)

    def home_all_axes(self) -> None:
        execute_gcode("G38", 120)
        return None

    def home_single_axes(self, axis: int):
        return None


    def home_axis(self, axis: int) -> None:
        """Home a single axis (or every axis when ``axis == -1``).

        Always switches to ``MODE_MANUAL`` first so a stale
        ``MODE_AUTO`` does not silently swallow the home command.
        ``axis == -1`` triggers a sweep across the canonical three
        Cartesian axes (X, Y, Z); a non-``-1`` value homes a single
        axis.
        """
        warnings.warn(
            "home_axis() is deprecated and will be removed "
            "Use home_all_axes() or home_single_axes() instead.",
            DeprecationWarning,
            stacklevel=2
        )

        execute_sync_cmd("mode", 0, getattr(linuxcnc, "MODE_MANUAL", 1))
        if axis == -1:
            for i in range(3):
                execute_sync_cmd("home", 3, i)
            return
        execute_sync_cmd("home", 3, axis)

    # ------------------------------------------------------------------ #
    # Read path — clean state facade (no linuxcnc.NML leakage)            #
    # ------------------------------------------------------------------ #

    def get_state(self) -> MachineState:
        """Translate the linuxcnc ``task_state`` / ``estop`` /
        ``interp_state`` triple into a clean :class:`MachineState`.

        Priority order (mirrors
        ``frontend/src/stores/stateFacade.js::systemState``):

          OFFLINE → ESTOP → POWER_OFF → PAUSED → RUNNING →
          LOADED → IDLE → FAILURE.

        Returns :attr:`MachineState.OFFLINE` when:

          * the NML stat channel has not connected yet
            (``connection.get_machine_stat() is None``);
          * the stat object raises while we try to read it
            (mock-vs-real split, ``getattr(..., default)`` is
            the same defensive pattern used in
            ``routers/servo_thread.py::get_current_state``).

        The ``linuxcnc.STATE_*`` / ``INTERP_*`` constants are
        read via ``getattr(..., default)`` so a build that
        omits one of them degrades to the offline branch
        rather than crashing the request handler.
        """
        stat = connection.get_machine_stat()
        if stat is None:
            return MachineState.OFFLINE

        try:
            stat.poll()
            task_state = getattr(stat, "task_state", 0)
            estop = getattr(stat, "estop", 0)
            interp_state = getattr(stat, "interp_state", 0)
        except Exception:  # noqa: BLE001 - defensive, see docstring
            return MachineState.OFFLINE

        # E-stop bit wins over ``task_state`` — the operator
        # panel must always show ``Estop`` while the bit is set
        # even if LinuxCNC has not yet flipped ``task_state``.
        if estop == 1 or task_state == getattr(linuxcnc, "STATE_ESTOP", 1):
            return MachineState.ESTOP

        # ``STATE_OFF`` and ``STATE_ESTOP_RESET`` both surface
        # as ``POWER_OFF``: from the operator's point of view
        # the machine is not currently executing and not ready
        # to take a cut until they press Power.
        if task_state in (
            getattr(linuxcnc, "STATE_OFF", 3),
            getattr(linuxcnc, "STATE_ESTOP_RESET", 2),
        ):
            return MachineState.POWER_OFF

        if task_state == getattr(linuxcnc, "STATE_ON", 4):
            # ``STATE_ON`` covers the whole "powered" range; the
            # interpreter state disambiguates which sub-state
            # the operator actually sees.
            if interp_state == getattr(linuxcnc, "INTERP_PAUSED", 3):
                return MachineState.PAUSED
            if interp_state in (
                getattr(linuxcnc, "INTERP_READING", 2),
                getattr(linuxcnc, "INTERP_WAITING", 4),
            ):
                return MachineState.RUNNING
            # Interpreter idle while a file is selected — the
            # canonical LinuxCNC "loaded but not running" state.
            # The dashboard renders the dedicated ``Loaded``
            # branch with its own Start button.
            if getattr(stat, "file", ""):
                return MachineState.LOADED
            return MachineState.IDLE

        # Unknown ``task_state`` — defensive default rather than
        # crashing the WebSocket loop on a future LinuxCNC
        # build that adds a new state we don't know about yet.
        return MachineState.FAILURE

    def get_state_snapshot(self) -> dict:
        """JSON-serialisable snapshot for the API / WebSocket.

        Shape is deliberately stable::

            {
                "state": "idle",            # clean enum string
                "raw_task_state": 4,        # diagnostic-only
                "raw_estop": 0,
                "raw_interp_state": 1,
                "file": "",                 # loaded file path
                "homed": [0, 0, 0],         # per-axis flags
            }

        ``raw_*`` fields are intentionally prefixed so a future
        refactor can drop them without breaking the wire format.
        The clean ``state`` field is what every consumer should
        read; the raw fields exist only for the diagnostic panel
        and the migration window.
        """
        empty = {
            "state": MachineState.OFFLINE.value,
            "raw_task_state": 0,
            "raw_estop": 0,
            "raw_interp_state": 0,
            "file": "",
            "homed": [0, 0, 0],
        }

        stat = connection.get_machine_stat()
        if stat is None:
            return dict(empty)

        try:
            stat.poll()
            task_state = int(getattr(stat, "task_state", 0))
            estop = int(getattr(stat, "estop", 0))
            interp_state = int(getattr(stat, "interp_state", 0))
            file_name = getattr(stat, "file", "") or ""
            homed = list(getattr(stat, "homed", [0, 0, 0]))
        except Exception:  # noqa: BLE001 - defensive, see docstring
            return dict(empty)

        return {
            "state": self.get_state().value,
            "raw_task_state": task_state,
            "raw_estop": estop,
            "raw_interp_state": interp_state,
            "file": file_name,
            "homed": homed,
        }

    def run_mdi(self, command: str) -> None:
        """Dispatch a single MDI command.

        Switches the task mode to ``MODE_MDI`` before issuing the
        command so a stale ``MODE_AUTO`` does not silently swallow
        the dispatch. The timeout (``5s``) is the historical
        ``mode`` round-trip budget.
        """
        logger.info("Running MDI: %s", command)
        execute_sync_cmd("mode", 5, getattr(linuxcnc, "MODE_MDI", 3))
        execute_sync_cmd("mdi", 0, command)

    def turn_machine_on(self) -> None:
        """Powers on the machine. Fails if ESTOP is active."""
        stat = connection.get_machine_stat()
        stat.poll()
        if getattr(stat, 'task_state', 0) == getattr(linuxcnc, "STATE_ESTOP", 1):
            raise RuntimeError("Cannot turn on machine while in E-STOP.")

        execute_sync_cmd("state", 3, getattr(linuxcnc, "STATE_ON", 3))

    def trigger_estop(self) -> None:
        """Forces an immediate emergency stop."""
        execute_sync_cmd("state", 3, getattr(linuxcnc, "STATE_ESTOP", 1))

    def get_machine_stat(self):
        warnings.warn(
            "MachineControlService.get_machine_stat() is deprecated "
            "and will be removed — use get_state_snapshot() instead.",
            DeprecationWarning,
            stacklevel=2
        )
        return connection.get_machine_stat()

    def get_machine_cmd(self):
        warnings.warn(
            "MachineControlService.get_machine_cmd() is deprecated "
            "and will be removed — dispatch helpers in this facade "
            "are the supported entry point.",
            DeprecationWarning,
            stacklevel=2
        )
        return connection.get_machine_cmd()

    def get_machine_error(self):
        warnings.warn(
            "MachineControlService.get_machine_error() is deprecated "
            "and will be removed — error-channel handling will move "
            "to its own facade.",
            DeprecationWarning,
            stacklevel=2
        )
        return connection.get_machine_error()

    def is_linuxcnc_connected(self) -> bool:
        warnings.warn(
            "MachineControlService.is_linuxcnc_connected() is "
            "deprecated and will be removed — the offline branch "
            "is exposed through get_state() == MachineState.OFFLINE.",
            DeprecationWarning,
            stacklevel=2
        )
        return connection.is_linuxcnc_connected()

    def get_spindle(self):
        pass

    def get_heater(self):
        pass
    def get_fan(self):
        pass
    def get_extruder(self):
        pass

    def set_heater_temperature(self, heater_temperature: int) -> None:
        pass

    def set_fan_speed(self, fan_speed: int) -> None:
        pass
    def set_spindle_speed(self):
        pass

    def set_spindle_override_relative(self):
        pass

    def set_spindle_override_absolute(self):
        pass

    LOAD_TIMEOUT_S = 5.0

    def _is_program_loaded(self) -> bool:
        """Helper to safely check if the interpreter has a file loaded."""
        stat = get_machine_stat()
        if not stat:
            return False
        if hasattr(stat, 'poll'):
            stat.poll()
        return bool(getattr(stat, "file", ""))

    def _await_load(self, target_path: str) -> None:
        """Polls LinuxCNC memory until the file pointer matches the target."""
        deadline = time.monotonic() + self.LOAD_TIMEOUT_S
        while True:
            stat = get_machine_stat()
            if stat:
                if hasattr(stat, 'poll'):
                    stat.poll()
                current = str(getattr(stat, "file", "") or "")
                if current == target_path:
                    return

            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"LinuxCNC did not load '{target_path}' within {self.LOAD_TIMEOUT_S}s"
                )
            time.sleep(0.05)

    def load_program(self, file_path: str) -> None:
        execute_sync_cmd("program_open", self.LOAD_TIMEOUT_S, file_path)
        self._await_load(file_path)

    def unload_program(self) -> None:
        execute_sync_cmd("program_open", self.LOAD_TIMEOUT_S, "")

    def start_program(self, line_number: int = 0) -> None:
        if not self._is_program_loaded():
            raise RuntimeError("No program loaded. Load a file before starting.")

        execute_sync_cmd("mode", 3, getattr(linuxcnc, "MODE_AUTO", 2))
        execute_sync_cmd("auto", 0, getattr(linuxcnc, "AUTO_RUN", 0), line_number)

    def stop_program(self) -> None:
        execute_sync_cmd("abort")

    def pause_program(self) -> None:
        execute_sync_cmd("auto", 0, getattr(linuxcnc, "AUTO_PAUSE", 1))

    def resume_program(self) -> None:
        execute_sync_cmd("auto", 0, getattr(linuxcnc, "AUTO_RESUME", 2))

    def progress_program(self, stat=None) -> ProgramProgressResponse:
        stat = get_machine_stat()

        if stat is None:
            return ProgramProgressResponse(
                current_line=0,
                motion_line=0,
                total_lines=0,
                file="",
                interp_state=int(getattr(linuxcnc, "INTERP_IDLE", 1)),
            )


        poll = getattr(stat, "poll", None)
        if callable(poll):
            poll()

        file_path = str(getattr(stat, "file", "") or "")
        current_line = int(getattr(stat, "current_line", 0) or 0)
        motion_line = int(getattr(stat, "motion_line", 0) or 0)
        interp_state = int(
            getattr(stat, "interp_state", getattr(linuxcnc, "INTERP_IDLE", 1))
            or getattr(linuxcnc, "INTERP_IDLE", 1)
        )

        return ProgramProgressResponse(
            current_line=max(0, current_line),
            motion_line=max(0, motion_line),
            total_lines=max(0, lookup_line_count(file_path)),
            file=file_path,
            interp_state=interp_state,
        )




# ---------------------------------------------------------------------------
# Slow-channel telemetry collectors (base-thread snapshot helpers)
# ---------------------------------------------------------------------------
#
# These used to live inside the module routers (``modules/tools/router.py``
# and ``modules/temperature/router.py``) — the base-thread snapshot
# router then imported them from the routers, which forced the snapshot
# path to depend on the operator-facing MDI surface. Centralising them
# here makes the service layer the single source of truth for the
# 1 Hz dashboard payload and lets the routers stay thin HTTP wrappers.
#
# The helper functions also abstract the ``linuxcnc_mock._machine_state``
# access so the snapshot router never imports the mock module.


# Tools that surface runtime heat state (``actual`` / ``target``)
# read from the mock's ``temperatures`` dict. Spindle / laser tools
# are absent from that dict.
_HEATING_TOOL_TYPES = frozenset({"extruder", "heated_bed"})


def _get_linuxcnc_mock():
    """Lazily resolve ``hardware.linuxcnc_mock``.

    The mock is imported lazily so this module does not pull in the
    hardware package at import time. The same pattern is used in
    :mod:`hardware.linuxcnc_mock` itself to break the
    ``hardware`` → ``modules.temperature`` → ``hardware`` cycle.
    """
    from hardware import linuxcnc_mock
    return linuxcnc_mock


def read_temperature(sensor_id: str) -> Optional[Dict[str, float]]:
    """Return the live temperature reading for ``sensor_id``.

    Returns ``None`` when the sensor has not been seeded yet (e.g. a
    test boot without a ``hardware.json`` that names it). Routers
    only need to know the answer is "no data" — the underlying
    ``_machine_state`` dictionary is a private detail.
    """
    if not isinstance(sensor_id, str) or not sensor_id:
        return None
    mock = _get_linuxcnc_mock()
    with mock._machine_state.lock:  # noqa: SLF001
        reading = mock._machine_state.temperatures.get(sensor_id)
    if not reading:
        return None
    return {
        "actual": reading.get("actual", 0.0),
        "target": reading.get("target", 0.0),
    }


def read_spindle_telemetry(tool_id: str) -> Optional[Dict[str, object]]:
    """Return the live spindle telemetry for ``tool_id``.

    Returns ``None`` when no telemetry has arrived yet. The dict
    shape mirrors ``linuxcnc_mock._machine_state.spindle_actual``
    entries — ``actual`` / ``is_connected`` / ``error_count``.
    """
    if not isinstance(tool_id, str) or not tool_id:
        return None
    mock = _get_linuxcnc_mock()
    with mock._machine_state.lock:  # noqa: SLF001
        reading = mock._machine_state.spindle_actual.get(tool_id)
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


def collect_tools() -> List[dict]:
    """Return the active ``hardware.json`` tool list with runtime state.

    Public helper used by the base-thread snapshot
    (``routers/base_thread.py``) so the slow-channel surface stays
    byte-for-byte identical. Returns an empty list when
    ``hardware.json`` is missing — mirrors the temperature module's
    empty-state behaviour so the ToolPanel renders the "No tools
    configured yet" placeholder instead of failing to mount.
    """
    raw = load_active_tools()
    return [_overlay_runtime_state(tool) for tool in raw]


def collect_sensors() -> Dict[str, Dict[str, float]]:
    """Read the live sensor dict from the stat channel.

    Returns a plain dict (sensor name -> ``{actual, target}``) so the
    base-thread snapshot can serialise it the same way. Falls back to
    ``{}`` when the NML channel is offline — the dashboard's
    empty-state UI handles the no-data case cleanly.
    """
    stat = get_machine_stat()
    if stat is None:
        return {}
    poll = getattr(stat, "poll", None)
    if callable(poll):
        poll()
    sensors = getattr(stat, "temperatures", None) or {}
    return {name: dict(values) for name, values in sensors.items()}

# this should be here
# def set_target(name: str, req: SetTargetRequest) -> SetTargetResponse:
#     """Set the target temperature for ``name``.
#
#     The ``sensor_name`` field in the body is accepted but ``name``
#     from the URL takes precedence — the URL is the canonical
#     identifier and the body field is kept for backward compatibility
#     with the legacy ``POST /api/v1/machine/temperature`` payload.
#     """
#     if not name or not isinstance(name, str):
#         raise HTTPException(
#             status_code=400,
#             detail="Sensor name must be a non-empty string",
#         )
#     if name != req.sensor_name:
#         logger.debug(
#             "sensor_name in body (%r) differs from URL (%r); URL wins",
#             req.sensor_name,
#             name,
#         )
#     try:
#         result = execute_sync_cmd("set_temperature", 0, name, req.target)
#     except HTTPException:
#         # ``execute_sync_cmd`` already produces actionable HTTP errors.
#         raise
#     except Exception as exc:  # noqa: BLE001 - defensive: surface any failure
#         logger.error("set_temperature(%s, %s) failed: %s", name, req.target, exc)
#         raise HTTPException(status_code=500, detail=str(exc))
#
#     return SetTargetResponse(
#         status=result.get("status", "success"),
#         sensor_name=name,
#         target=req.target,
#     )

# ---------------------------------------------------------------------------
# Module-level singletons
# ---------------------------------------------------------------------------


from hardware.device_config_mapper import (
    DeviceConfigMapper as _DeviceConfigMapper,
)
from hardware.hal_subscription_manager import (
    HalSubscriptionManager as _HalSubscriptionManager,
)

_machine_service: Optional[MachineService] = None
_machine_control_service: Optional[MachineControlService] = None


def get_machine_service() -> MachineService:
    """Lazy module-level singleton (HAL-pin facade).

    Mirrors the :class:`backend.hardware.connection._LazyChannel`
    pattern: the instance survives across requests and resets on
    ``uvicorn --reload``. The first call composes a default
    :class:`DeviceConfigMapper` (reads
    ``machine_config/active/hardware.json``) and
    :class:`HalSubscriptionManager`.
    """
    global _machine_service
    if _machine_service is None:
        _machine_service = MachineService(
            mapper=_DeviceConfigMapper(),
            hal_sub_mgr=_HalSubscriptionManager(),
        )
    return _machine_service


def get_machine_control_service() -> MachineControlService:
    """Lazy module-level singleton (machine-business facade)."""
    global _machine_control_service
    if _machine_control_service is None:
        _machine_control_service = MachineControlService()
    return _machine_control_service

class ProgramProgressResponse(BaseModel):
    """Progress snapshot for the active G-code program.

    Returned by ``GET /api/v1/modules/program/progress`` so the dashboard
    can poll once a second without saturating NML. ``total_lines``
    comes from a backend-side line-count cache populated when the
    file is loaded; ``current_line`` and ``motion_line`` come
    straight from ``linuxcnc.stat``. ``interp_state`` mirrors the
    raw integer so the widget can decide whether to keep polling.
    """

    current_line: int = Field(
        ...,
        ge=0,
        description=(
            "Line the RS274NGC interpreter is currently reading. "
            "Mirrors ``stat.current_line``."
        ),
    )
    motion_line: int = Field(
        ...,
        ge=0,
        description=(
            "Source line motion is currently executing. Mirrors "
            "``stat.motion_line``; ``0`` when the interpreter is idle."
        ),
    )
    total_lines: int = Field(
        ...,
        ge=0,
        description=(
            "Total line count of the loaded G-code file, populated "
            "from a backend-side cache at ``program_open`` time. "
            "``0`` when no file is loaded or the file was unreadable."
        ),
    )
    file: str = Field(
        ...,
        description=(
            "Absolute path of the loaded G-code file (``stat.file``) "
            "or empty string when nothing is loaded."
        ),
    )
    interp_state: int = Field(
        ...,
        description=(
            "Current ``linuxcnc.INTERP_*`` state. ``1`` IDLE, "
            "``2`` READING, ``3`` PAUSED, ``4`` WAITING."
        ),
    )

__all__ = [
    "MachineState",
    "MachineService",
    "MachineControlService",
    "get_machine_service",
    "get_machine_control_service",
    "collect_tools",
    "collect_sensors",
    "read_temperature",
    "read_spindle_telemetry",
    "ProgramProgressResponse"
]