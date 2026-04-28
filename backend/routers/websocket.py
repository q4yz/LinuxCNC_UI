import asyncio
import json
import logging
from datetime import datetime
from typing import List
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from hardware import get_machine_stat, get_machine_error

logger = logging.getLogger("backend.routers.websocket")
router = APIRouter(prefix="/ws", tags=["websocket"])


class ConnectionManager:
    """Manages active WebSocket connections to broadcast data."""
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        """Accepts a new connection and adds it to the pool."""
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket Client connected. Total clients: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        """Removes a connection from the pool."""
        self.active_connections.remove(websocket)
        logger.info(f"WebSocket Client disconnected. Total clients: {len(self.active_connections)}")

    async def broadcast(self, message: str):
        """Sends a text message to all active clients."""
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception as e:
                logger.error(f"Error broadcasting to client: {e}")

manager = ConnectionManager()


def parse_status() -> dict:
    """
    Reads the current machine status from the LinuxCNC stat object
    and formats it as a JSON-serializable dictionary.
    """
    machine_stat = get_machine_stat()
    
    # Safe fallback if attributes don't exist in mock yet
    interp_state = getattr(machine_stat, 'interp_state', 0)
    current_line = getattr(machine_stat, 'current_line', 0)
    g5x_index = getattr(machine_stat, 'g5x_index', 1)
    
    return {
        "type": "status",
        "data": {
            "task_state": machine_stat.task_state,
            "estop": machine_stat.estop,
            "task_mode": machine_stat.task_mode,
            "position": machine_stat.position,
            "actual_position": machine_stat.actual_position,
            "state": machine_stat.state,
            "file": machine_stat.file,
            "homed": machine_stat.homed,
            "interp_state": interp_state,
            "current_line": current_line,
            "g5x_index": g5x_index
        }
    }


async def telemetry_loop():
    """
    Background loop that continuously polls the CNC machine at 10Hz
    and broadcasts the state and any new errors to all connected WebSockets.
    """
    machine_stat = get_machine_stat()
    machine_error = get_machine_error()

    while True:
        try:
            # Poll status
            machine_stat.poll()
            
            # Poll errors
            error = machine_error.poll()
            if error and manager.active_connections:
                kind, text = error
                error_payload = {
                    "type": "error",
                    "data": {
                        "kind": kind,
                        "text": text,
                        "time": datetime.now().isoformat()
                    }
                }
                await manager.broadcast(json.dumps(error_payload))

            # Broadcast status
            if manager.active_connections:
                await manager.broadcast(json.dumps(parse_status()))

        except Exception as e:
            logger.error(f"Error in telemetry loop: {e}")
        
        # Sleep for 100ms (10Hz refresh rate)
        await asyncio.sleep(0.1)


@router.websocket("/telemetry")
async def websocket_telemetry(websocket: WebSocket):
    """
    The main WebSocket endpoint for UI clients to connect to
    for real-time machine telemetry.
    """
    await manager.connect(websocket)
    try:
        while True:
            # We don't expect messages from the client on this channel,
            # but we need to wait for a disconnect
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)