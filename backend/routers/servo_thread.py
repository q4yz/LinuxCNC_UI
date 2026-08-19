"""Servo-thread telemetry stream.

LinuxCNC's runtime uses two parallel threads:
* a fast servo thread (position controllers, trajectory planner)
* a slower base thread (UI updates, status reporting).
"""
import asyncio
import json
import logging
from typing import List, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from hardware import get_machine_stat, get_machine_error
from hardware.connection import read_error_history
from mapper.servo_thread_state_mapper import ServoThreadStateMapper
from models.servo_thread import WSEnvelope, ServoThreadStateResponse
from services.console_logger import LogLevel, get_console_logger

# Import your externalized models and mapper
from dtos.servo_thread_state import ServoThreadStateDTO


logger = logging.getLogger("backend.routers.servo_thread")
router = APIRouter(prefix="/ws", tags=["Telemetry WebSockets"])


# ---------------------------------------------------------------------------
# Connection Manager & Global State Tracking
# ---------------------------------------------------------------------------

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
_last_broadcast_state: Optional[ServoThreadStateDTO] = None


# ---------------------------------------------------------------------------
# Telemetry Loop & WebSocket
# ---------------------------------------------------------------------------

async def telemetry_loop():
    """
    Background loop that continuously polls the CNC machine at 10Hz
    and broadcasts the state diff to all connected WebSockets.
    """
    global _last_broadcast_state
    console_logger = get_console_logger()

    while True:
        try:
            machine_stat = get_machine_stat()
            machine_error = get_machine_error()

            # Handle offline / disconnected state
            if machine_stat is None or machine_error is None:
                if manager.active_connections:
                    current_dto = ServoThreadStateMapper.from_stat(None, read_error_history())
                    diff_resp = ServoThreadStateMapper.get_diff_response(current_dto, _last_broadcast_state)

                    delta_dict = diff_resp.model_dump(exclude_none=True)
                    if delta_dict:
                        await manager.broadcast(
                            json.dumps({"type": "delta", "data": delta_dict})
                        )
                        _last_broadcast_state = current_dto
                await asyncio.sleep(0.1)
                continue

            # Poll LinuxCNC stat with transient error handling
            try:
                machine_stat.poll()
            except OSError as exc:
                logger.debug("stat.poll() raised OSError (%s); skipping tick", exc)
                await asyncio.sleep(0.1)
                continue
            except RuntimeError as exc:
                logger.debug("stat.poll() raised RuntimeError (%s); skipping tick", exc)
                await asyncio.sleep(0.1)
                continue

            # Poll LinuxCNC error channel
            try:
                error = machine_error.poll()
            except (OSError, RuntimeError) as exc:
                logger.debug("error_channel.poll() raised %s (%s); skipping tick", type(exc).__name__, exc)
                await asyncio.sleep(0.1)
                continue

            if error and manager.active_connections:
                kind, text = error
                console_logger.log_response(
                    f"Machine error ({kind}): {text}",
                    level=LogLevel.ERROR,
                )

            current_dto = ServoThreadStateMapper.from_stat(machine_stat, read_error_history())
            diff_resp = ServoThreadStateMapper.get_diff_response(current_dto, _last_broadcast_state)

            if diff_resp.model_dump(exclude_none=True) and manager.active_connections:

                envelope = WSEnvelope[ServoThreadStateResponse]( type="delta",data=diff_resp)

                payload_json = envelope.model_dump_json(exclude_none=True)

                await manager.broadcast(payload_json)
                console_logger.log_telemetry(payload_json)

                _last_broadcast_state = current_dto


        except Exception as e:
            logger.error(f"Error in telemetry loop: {e}")

        # Sleep for 100ms (10Hz refresh rate)
        await asyncio.sleep(0.1)


async def _dispatch_inbound(websocket: WebSocket, msg: dict) -> None:
    """Route a JSON command received over the telemetry socket."""
    mtype = msg.get("type")

    if mtype == "jog_keepalive":
        from modules.axis.jog_service import jog_keepalive
        axes = msg.get("axes") or []
        if not isinstance(axes, list):
            logger.warning("jog_keepalive: 'axes' must be a list, got %r", type(axes))
            return
        jog_keepalive([int(a) for a in axes])
        return

    if mtype == "jog_axis":
        from modules.axis.jog_service import jog_axis
        velocities = msg.get("velocities") or {}
        if not isinstance(velocities, dict):
            logger.warning("jog_axis: 'velocities' must be a dict, got %r", type(velocities))
            return
        distance = float(msg.get("distance") or 0)
        coerced = {}
        for axis, velocity in velocities.items():
            try:
                coerced[int(axis)] = float(velocity)
            except (TypeError, ValueError):
                logger.warning("jog_axis: dropping bad axis/velocity pair %r=%r", axis, velocity)
        jog_axis(coerced, distance)
        return

    if mtype == "jog_stop":
        from modules.axis.jog_service import jog_stop
        axes = msg.get("axes") or []
        if not isinstance(axes, list):
            logger.warning("jog_stop: 'axes' must be a list, got %r", type(axes))
            return
        jog_stop([int(a) for a in axes])
        return

    logger.debug("unknown WS message type: %r", mtype)


# --- THE DUMMY ENDPOINT ---
@router.get(
    "/_schema/telemetry",
    response_model=WSEnvelope[ServoThreadStateResponse],
    summary="Export WebSocket Schema (Do Not Call)",
    description="This is a dummy endpoint used strictly to force the WSEnvelope schema into the OpenAPI spec for frontend code generation.",
    include_in_schema=True # Set to False if you want to hide it from Swagger UI but keep it in openapi.json
)
def _export_ws_schema():
    """Dummy endpoint to export WebSocket payload schemas."""
    raise NotImplementedError("This endpoint is for schema generation only.")

@router.websocket("/telemetry")
async def websocket_telemetry(websocket: WebSocket):
    """
    The main WebSocket endpoint for UI clients to connect to
    for real-time machine telemetry and to send jog commands.
    """
    global _last_broadcast_state
    await manager.connect(websocket)
    try:
        # Create full DTO for the very first connection payload
        machine_stat = get_machine_stat()
        current_dto = ServoThreadStateMapper.from_stat(machine_stat, read_error_history())
        full_response = ServoThreadStateMapper.to_response(current_dto)

        envelope = WSEnvelope[ServoThreadStateResponse](
            type="full_state",
            data=full_response
        )
        await websocket.send_text(envelope.model_dump_json())

        _last_broadcast_state = current_dto

        while True:
            text = await websocket.receive_text()
            try:
                payload = json.loads(text)
            except ValueError:
                logger.warning("ignoring non-JSON WS message: %r", text[:120])
                continue
            if not isinstance(payload, dict):
                logger.warning("ignoring non-object WS message: %r", payload)
                continue
            try:
                await _dispatch_inbound(websocket, payload)
            except Exception as exc:  # noqa: BLE001
                logger.exception("WS inbound dispatch failed: %s", exc)

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)
        raise