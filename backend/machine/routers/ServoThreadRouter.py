"""Servo-thread telemetry stream.

LinuxCNC's runtime uses two parallel threads:
* a fast servo thread (position controllers, trajectory planner)
* a slower base thread (UI updates, status reporting).
"""
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from models.ServoThreadStateResponse import WSEnvelope, ServoThreadStateResponse
from services.ServoThreadService import get_servo_thread_service

logger = logging.getLogger("backend.routers.servo_thread")
router = APIRouter(prefix="/ws", tags=["Telemetry WebSockets"])


# --- THE DUMMY ENDPOINT ---
@router.get(
    "/_schema/telemetry",
    response_model=WSEnvelope[ServoThreadStateResponse],
    summary="Export WebSocket Schema (Do Not Call)",
    description="This is a dummy endpoint used strictly to force the WSEnvelope schema into the OpenAPI spec for frontend code generation.",
    include_in_schema=True
)
def _export_ws_schema():
    """Dummy endpoint to export WebSocket payload schemas."""
    raise NotImplementedError("This endpoint is for schema generation only.")


# --- THE WEBSOCKET ENDPOINT ---
@router.websocket("/telemetry")
async def websocket_telemetry(websocket: WebSocket):
    """
    The main WebSocket endpoint for UI clients to connect to
    for real-time machine telemetry and to send jog commands.
    """
    service = get_servo_thread_service()
    await service.connect(websocket)

    try:
        # Send full initial state immediately upon connection
        initial_payload = service.get_initial_state_json()
        await websocket.send_text(initial_payload)

        # Listen for inbound commands
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
                await service.dispatch_inbound(websocket, payload)
            except Exception as exc:
                logger.exception("WS inbound dispatch failed: %s", exc)

    except WebSocketDisconnect:
        service.disconnect(websocket)
    except Exception as e:
        logger.error(f"Unexpected WS error: {e}")
        service.disconnect(websocket)
        raise