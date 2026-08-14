"""Servo-thread telemetry stream.

LinuxCNC's runtime uses two parallel threads:

* a fast **servo thread** that handles time-critical work
  (position controllers, trajectory planner);
* a slower **base thread** that handles bookkeeping (UI updates,
  status reporting).

The web UI mirrors that split:

* this WebSocket is the "servo thread" — a 10 Hz broadcast stream
  carrying estop, task_state, position, errors, and anything the
  DRO / status panels need on every frame, plus a bidirectional
  channel for jog commands (``jog_axis`` / ``jog_keepalive`` /
  ``jog_stop``) so a continuous jog does not spam the REST layer;
* the partner endpoint ``/api/v1/base-thread/snapshot`` is the
  "base thread" — one round-trip per second collects every slow
  stream the dashboard cares about (program progress, temperature
  sensors, tool list) in a single payload.

The ``/ws/telemetry`` URL and the ``websocket_telemetry`` /
``telemetry_loop`` identifiers are preserved across the rename so
the frontend's URL surface stays intact.
"""
import asyncio
from copy import deepcopy
import json
import logging
from datetime import datetime
from typing import List
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from hardware import get_machine_stat, get_machine_error, linuxcnc
from hardware import linuxcnc_mock
from services.console_logger import LogLevel, get_console_logger

logger = logging.getLogger("backend.routers.servo_thread")
router = APIRouter(prefix="/ws", tags=["Telemetry WebSockets"])


class ConnectionManager:
    """Manages active WebSocket connections to broadcast data."""
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket Client connected. Total clients: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        logger.info(f"WebSocket Client disconnected. Total clients: {len(self.active_connections)}")

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception as e:
                logger.error(f"Error broadcasting to client: {e}")

manager = ConnectionManager()
last_broadcast_state: dict = {}


def get_dict_diff(new_dict: dict, old_dict: dict) -> dict:
    diff = {}

    for key, new_value in new_dict.items():
        old_value = old_dict.get(key)
        if is_nested(new_value) and is_nested(old_value):
            nested_diff = get_dict_diff(new_value, old_value)
            diff[key] = nested_diff
        elif new_value != old_value:
            diff[key] = new_value
        else:
            pass
    return diff


def is_nested(new_value) -> bool:
    return isinstance(new_value, dict)


def _offline_state_snapshot() -> dict:
    """Return a safe "LinuxCNC not running" telemetry payload.

    Used by :func:`get_current_state` when the NML status channel
    has not yet connected — every key the frontend reads is
    present so the WebSocket payload schema is stable. The values
    map to ``SystemState.ESTOP`` on the frontend so the operator
    sees the existing red "Estop" chip rather than a blank screen
    or a stream of crashes.

    The progress counters (``current_line`` / ``total_lines``) live
    on the dedicated ``GET /api/v1/modules/program/progress``
    endpoint so the dashboard can poll them at 1 Hz without the
    10 Hz telemetry loop saturating NML. The broadcast no longer
    carries them.

    Sensors moved to the base-thread snapshot
    (``routers/base_thread.py``) for the same reason; the 10 Hz
    ``/ws/telemetry`` stream only carries the time-critical
    fields the DRO / status panels need on every frame.

    Program progress moved to the base-thread snapshot as well
    (``progress.current_line`` / ``progress.motion_line`` /
    ``progress.total_lines``). The 1 Hz snapshot is the canonical
    surface for every slow stream; the WebSocket no longer carries
    any of them.
    """
    return {
        "task_state": getattr(linuxcnc, "STATE_ESTOP", 1),
        "estop": 1,
        "task_mode": getattr(linuxcnc, "MODE_MANUAL", 1),
        "position": [0.0] * 9,
        "actual_position": [0.0] * 9,
        "relative_position": [0.0] * 9,
        "state": 1,
        "file": "",
        "homed": [0, 0, 0],
        "interp_state": getattr(linuxcnc, "INTERP_IDLE", 1),
        "g5x_index": 1,
    }


def get_current_state() -> dict:
    """
    Reads the current machine status from the LinuxCNC stat object
    and formats it as a JSON-serializable dictionary.

    Returns a safe "offline" snapshot when the NML status channel
    has not yet connected (LinuxCNC not running). The frontend's
    ``machineStore.systemState`` getter maps the ``STATE_ESTOP``
    payload to ``SystemState.ESTOP`` so operators get a clear
    "machine offline" indicator without the backend crashing.
    """
    machine_stat = get_machine_stat()
    if machine_stat is None:
        return _offline_state_snapshot()
    # Refresh the cached snapshot so callers that invoke this
    # function outside the telemetry loop (tests, the snapshot
    # endpoint) see the latest program state. The loop also calls
    # ``poll()`` on every tick so this is a no-op there.
    machine_stat.poll()

    # Safe fallback if attributes don't exist in mock yet
    interp_state = getattr(machine_stat, 'interp_state', 0)
    g5x_index = getattr(machine_stat, 'g5x_index', 1)

    # Calculate Relative Work Coordinates for the DRO
    actual_position = getattr(machine_stat, 'actual_position', (0.0,) * 9)
    g5x_offset = getattr(machine_stat, 'g5x_offset', (0.0,) * 9)
    g92_offset = getattr(machine_stat, 'g92_offset', (0.0,) * 9)
    tool_offset = getattr(machine_stat, 'tool_offset', (0.0,) * 9)

    relative_position = []
    for i in range(len(actual_position)):
        g5x = g5x_offset[i] if g5x_offset and i < len(g5x_offset) else 0.0
        g92 = g92_offset[i] if g92_offset and i < len(g92_offset) else 0.0
        tool = tool_offset[i] if tool_offset and i < len(tool_offset) else 0.0
        rel_axis = actual_position[i] - g5x - g92 - tool
        relative_position.append(rel_axis)

    return {
        "task_state": machine_stat.task_state,
        "estop": machine_stat.estop,
        "task_mode": machine_stat.task_mode,
        "position": machine_stat.position,
        "actual_position": machine_stat.actual_position,
        "relative_position": relative_position,
        "state": machine_stat.state,
        "file": machine_stat.file,
        "homed": machine_stat.homed,
        "interp_state": interp_state,
        "g5x_index": g5x_index,
        # Bounded recent LinuxCNC error-channel history (max 100
        # entries, oldest dropped first). ``telemetry_loop`` keeps
        # this fresh on every poll so a reload / reconnect sees the
        # operator's last session's errors in the console panel.
        "errors": list(linuxcnc_mock._machine_state.errors),
    }


async def telemetry_loop():
    """
    Background loop that continuously polls the CNC machine at 10Hz
    and broadcasts the state and any new errors to all connected WebSockets.

    The channel helpers are re-evaluated *inside* the loop body so a
    late-connecting LinuxCNC daemon gets picked up on the next tick
    instead of crashing forever with ``AttributeError: 'NoneType'
    object has no attribute 'poll'``. ``get_current_state()`` is
    None-safe — it returns :func:`_offline_state_snapshot` while the
    channels are offline — so the frontend keeps receiving the safe
    ESTOP-shaped payload until LinuxCNC is reachable.
    """
    # Capture the logger once at the top of the loop so the
    # ``get_console_logger`` lock is not taken on every iteration.
    console_logger = get_console_logger()

    while True:
        global last_broadcast_state
        try:
            # Fetch inside the loop so a late-connecting LinuxCNC
            # is picked up on the next tick instead of crashing
            # forever with ``AttributeError: 'NoneType' has no
            # attribute 'poll'``.
            machine_stat = get_machine_stat()
            machine_error = get_machine_error()

            # Skip the poll entirely when either channel is offline.
            # ``get_current_state()`` is None-safe — it returns the
            # offline snapshot — so we can still push the operator-
            # facing "LinuxCNC not running" ESTOP state to any
            # active WebSocket clients.
            if machine_stat is None or machine_error is None:
                if manager.active_connections:
                    current_state = get_current_state()
                    if current_state != last_broadcast_state:
                        await manager.broadcast(
                            json.dumps({"type": "delta", "data": current_state})
                        )
                        last_broadcast_state.clear()
                        last_broadcast_state.update(deepcopy(current_state))
                await asyncio.sleep(0.1)
                continue

            # Poll status.
            #
            # The cpython linuxcnc bindings surface the C-level NML
            # "buffer empty" condition as ``poll()`` returning ``-1``
            # *without* raising — ctypes then logs ``error return
            # without exception set`` the next time a Python error is
            # raised anywhere on the same thread. We catch both the
            # explicit exception (linuxcnc.error is OSError-derived)
            # and the ctypes-level "return without exception set"
            # RuntimeError the binding can synthesise, and treat both
            # as a transient state: skip the broadcast for this tick
            # and let the loop retry on the next 100 ms cycle. The
            # outer ``except Exception`` is still a safety net for
            # anything unexpected, but with these two local handlers
            # the typical LinuxCNC-startup race no longer spams the
            # log at 10 Hz.
            try:
                machine_stat.poll()
            except OSError as exc:
                logger.debug(
                    "telemetry_loop: stat.poll() raised OSError (%s); "
                    "skipping this tick", exc,
                )
                await asyncio.sleep(0.1)
                continue
            except RuntimeError as exc:
                # ``error return without exception set`` is reported by
                # ctypes as a RuntimeError. Treat the same as OSError.
                logger.debug(
                    "telemetry_loop: stat.poll() raised RuntimeError (%s); "
                    "skipping this tick", exc,
                )
                await asyncio.sleep(0.1)
                continue

            current_state = get_current_state()

            # Poll errors. Same race applies — a fresh LinuxCNC task
            # may not have an error channel ready on the first few
            # ticks. Swallow the transient failure the same way.
            try:
                error = machine_error.poll()
            except (OSError, RuntimeError) as exc:
                logger.debug(
                    "telemetry_loop: error_channel.poll() raised %s (%s); "
                    "skipping this tick", type(exc).__name__, exc,
                )
                await asyncio.sleep(0.1)
                continue
            if error and manager.active_connections:
                kind, text = error
                timestamp = datetime.now().isoformat()
                # Mirror into the bounded error history so the
                # operator sees the backlog after a reconnect /
                # page reload — ``full_state`` carries ``errors``
                # populated by ``push_error``. ``hasattr`` guards
                # the mock-only method so a real ``error_channel``
                # implementation never breaks the broadcast path.
                if hasattr(linuxcnc_mock._machine_state, "push_error"):
                    linuxcnc_mock._machine_state.push_error(
                        kind, text, timestamp
                    )
                error_payload = {
                    "type": "error",
                    "data": {
                        "kind": kind,
                        "text": text,
                        "time": timestamp,
                    }
                }
                await manager.broadcast(json.dumps(error_payload))
                # Mirror the error to the persistent console history
                # so the operator can replay the session after the
                # browser is closed.
                console_logger.log_response(
                    f"Machine error ({kind}): {text}",
                    level=LogLevel.ERROR,
                )

            delta = get_dict_diff(current_state, last_broadcast_state)
            if delta and manager.active_connections:
                await manager.broadcast(json.dumps({"type": "delta", "data": delta}))
                # Mirror the delta to the persistent log as
                # ``TEL`` (telemetry) rows at DEBUG level so the
                # file does not need a noisy INFO entry for every
                # 100 ms heartbeat.
                console_logger.log_telemetry(json.dumps(delta))
                last_broadcast_state.clear()
                last_broadcast_state.update(deepcopy(current_state))

        except Exception as e:
            logger.error(f"Error in telemetry loop: {e}")

        # Sleep for 100ms (10Hz refresh rate)
        await asyncio.sleep(0.1)


async def _dispatch_inbound(websocket: WebSocket, msg: dict) -> None:
    """Route a JSON command received over the telemetry socket.

    The frontend sends commands (``jog_axis`` / ``jog_keepalive`` /
    ``jog_stop``) as JSON messages over the same open socket the
    telemetry loop uses for ``full_state`` / ``delta`` / ``error``
    broadcasts. This replaces the legacy ``POST /jog`` /
    ``POST /jog/keepalive`` / ``POST /jog/stop`` round-trips so a
    continuous jog does not spam four HTTP requests per axis per
    second (250 ms cadence) on top of the 10 Hz broadcast.

    Single source of truth: every dispatch calls the same
    ``ws_jog_*`` helper that the REST handlers use, so the WS
    and REST paths cannot drift apart. Unknown message types log
    a warning and are silently dropped — the broadcast is one-way
    and a stray inbound message must never crash the loop.
    """
    mtype = msg.get("type")
    if mtype == "jog_keepalive":
        from modules.axis.jog import ws_jog_keepalive
        axes = msg.get("axes") or []
        if not isinstance(axes, list):
            logger.warning("jog_keepalive: 'axes' must be a list, got %r", type(axes))
            return
        ws_jog_keepalive([int(a) for a in axes])
        return
    if mtype == "jog_axis":
        from modules.axis.jog import ws_jog_axis
        velocities = msg.get("velocities") or {}
        if not isinstance(velocities, dict):
            logger.warning("jog_axis: 'velocities' must be a dict, got %r", type(velocities))
            return
        distance = float(msg.get("distance") or 0)
        # Coerce keys to int (JSON dict keys are always strings)
        coerced = {}
        for axis, velocity in velocities.items():
            try:
                coerced[int(axis)] = float(velocity)
            except (TypeError, ValueError):
                logger.warning("jog_axis: dropping bad axis/velocity pair %r=%r", axis, velocity)
        ws_jog_axis(coerced, distance)
        return
    if mtype == "jog_stop":
        from modules.axis.jog import ws_jog_stop
        axes = msg.get("axes") or []
        if not isinstance(axes, list):
            logger.warning("jog_stop: 'axes' must be a list, got %r", type(axes))
            return
        ws_jog_stop([int(a) for a in axes])
        return
    # Unknown message types are logged at DEBUG so a curious
    # operator inspecting the log doesn't see noise on every frame.
    logger.debug("unknown WS message type: %r", mtype)


@router.websocket("/telemetry")
async def websocket_telemetry(websocket: WebSocket):
    """
    The main WebSocket endpoint for UI clients to connect to
    for real-time machine telemetry and to send jog commands.

    ``get_current_state()`` is None-safe (returns the offline
    snapshot when ``get_machine_stat()`` is ``None``), so the
    handler no longer calls ``machine_stat.poll()`` directly —
    that path used to crash with ``AttributeError`` while LinuxCNC
    was offline, and the disconnected-client cleanup only ran in
    the ``WebSocketDisconnect`` branch, leaking entries in
    ``manager.active_connections``. The new ``except Exception``
    guarantees the connection is removed on every disconnect
    path.
    """
    await manager.connect(websocket)
    try:
        # Never call ``machine_stat.poll()`` here — the helper
        # handles the offline case internally so the ``full_state``
        # payload matches the actual telemetry-loop shape.
        current_state = get_current_state()

        await websocket.send_text(json.dumps({"type": "full_state", "data": current_state}))

        last_broadcast_state.clear()
        last_broadcast_state.update(deepcopy(current_state))

        while True:
            # Wait for the next inbound message. JSON parse errors
            # are logged and ignored so a malformed client message
            # cannot crash the broadcast loop. ``receive_text()``
            # raises ``WebSocketDisconnect`` when the client closes
            # the socket, which the outer ``except`` handles.
            text = await websocket.receive_text()
            try:
                payload = json.loads(text)
            except ValueError:
                logger.warning(
                    "ignoring non-JSON WS message: %r", text[:120]
                )
                continue
            if not isinstance(payload, dict):
                logger.warning(
                    "ignoring non-object WS message: %r", payload
                )
                continue
            try:
                await _dispatch_inbound(websocket, payload)
            except Exception as exc:  # noqa: BLE001 — see comment below
                # A buggy command handler must not kill the socket.
                # The broadcast loop must keep running so the
                # ``full_state`` / ``delta`` stream survives a single
                # bad command. The watchdog still force-stops the
                # axis if the keep-alive stops pinging, so a
                # silently-discarded keep-alive is a safe failure
                # mode.
                logger.exception("WS inbound dispatch failed: %s", exc)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        # Catch-all so the connection cleanup still runs even
        # when ``get_current_state`` (or any other helper in
        # scope) raises something unexpected. Without this the
        # socket lingers in ``active_connections`` indefinitely.
        manager.disconnect(websocket)
        raise
