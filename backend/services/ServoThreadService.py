import asyncio
import json
import logging
from typing import List, Optional

from fastapi import WebSocket

from mappers.ServoThreadStateMapper import ServoThreadStateMapper
from models.ServoThreadStateResponse import WSEnvelope, ServoThreadStateResponse
from dtos.LinuxCNCError import LinuxCNCError, now_iso
from dtos.ServoThreadState import ServoThreadStateDTO
from services.AxisService import get_axis_service
from services.ConsoleLogger import LogLevel, get_console_logger
from services.StateService import get_state_service

logger = logging.getLogger("backend.services.servo_thread")


class ServoThreadService:
    """Manages WebSocket telemetry broadcasting and inbound command dispatching."""

    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self._last_broadcast_state: Optional[ServoThreadStateDTO] = None
        self.state_service = get_state_service()
        self.axis_service = get_axis_service()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket Client connected. Total clients: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"WebSocket Client disconnected. Total clients: {len(self.active_connections)}")

    async def broadcast(self, message: str):
        for connection in list(self.active_connections):
            try:
                await connection.send_text(message)
            except Exception as e:
                logger.error(f"Error broadcasting to client: {e}")
                self.disconnect(connection)

    def get_initial_state_json(self) -> str:
        """Generates the full state payload for a newly connected client."""
        stat = self.state_service.get_polled_stat()
        history = self.state_service.get_error_history()

        current_dto = ServoThreadStateMapper.from_stat(stat, history)
        full_response = ServoThreadStateMapper.to_response(current_dto)

        envelope = WSEnvelope[ServoThreadStateResponse](type="full_state", data=full_response)
        self._last_broadcast_state = current_dto
        return envelope.model_dump_json(exclude_none=True)

    def get_current_state(self) -> dict:
        """Return the full ``full_state`` payload as a dict."""
        stat = self.state_service.get_polled_stat()
        history = self.state_service.get_error_history()

        current_dto = ServoThreadStateMapper.from_stat(stat, history)
        full_response = ServoThreadStateMapper.to_response(current_dto)
        return full_response.model_dump(exclude_none=True)

    async def dispatch_inbound(self, websocket: WebSocket, msg: dict) -> None:
        """Route a JSON command received over the telemetry socket."""

        # Pass the message to the AxisService.
        # If it handles it, we are done.
        handled = await self.axis_service.dispatch_inbound(msg)
        if handled:
            return

        # You can chain other domain services here in the future
        # handled = await self.spindle_service.dispatch_inbound(msg)
        # if handled:
        #     return

        logger.debug("unknown WS message type: %r", msg.get("type"))

    async def telemetry_loop(self):
        """
        Background loop that continuously polls the CNC machine at 10Hz
        and broadcasts the state diff to all connected WebSockets.
        """
        console_logger = get_console_logger()

        while True:
            try:
                # 1. Fetch hardware state safely
                stat = self.state_service.get_polled_stat()
                history = self.state_service.get_error_history()

                # 2. Process and broadcast new errors instantly
                new_errors = self.state_service.drain_new_errors()
                if new_errors and self.active_connections:
                    for kind, text in new_errors:
                        self.state_service.record_error_to_mock(kind, text)

                        console_logger.log_response(f"Machine error ({kind}): {text}", level=LogLevel.ERROR)

                        payload = json.dumps({
                            "type": "error",
                            "data": LinuxCNCError(kind=int(kind), text=str(text), time=now_iso()).model_dump(),
                        })
                        await self.broadcast(payload)
                        console_logger.log_telemetry(payload)

                # 3. Compute delta and broadcast state diff
                current_dto = ServoThreadStateMapper.from_stat(stat, history)
                diff_resp = ServoThreadStateMapper.get_diff_response(current_dto, self._last_broadcast_state)
                delta_dict = diff_resp.model_dump(exclude_none=True)

                if delta_dict and self.active_connections:
                    payload_json = json.dumps({"type": "delta", "data": delta_dict})
                    await self.broadcast(payload_json)
                    console_logger.log_telemetry(payload_json)

                    self._last_broadcast_state = current_dto

            except Exception as e:
                logger.error(f"Error in telemetry loop: {e}")

            # Sleep for 100ms (10Hz refresh rate)
            await asyncio.sleep(0.1)


# Singleton Provider
_SERVICE_INSTANCE = None

def get_servo_thread_service() -> ServoThreadService:
    global _SERVICE_INSTANCE
    if _SERVICE_INSTANCE is None:
        _SERVICE_INSTANCE = ServoThreadService()
    return _SERVICE_INSTANCE