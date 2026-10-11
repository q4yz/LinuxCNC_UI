import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import WebSocket

from mappers.ServoThreadStateMapper import ServoThreadStateMapper
from models.ServoThreadStateResponse import WSEnvelope, ServoThreadStateResponse
from dtos.LinuxCNCError import LinuxCNCError, now_iso
from dtos.ServoThreadState import ServoThreadStateDTO
from services.AxisService import get_axis_service
from services.ConsoleLogger import LogLevel, get_console_logger
from services.StateService import get_state_service
from core.NonRepeatingLogger import NonRepeatingLogger
from hardware.Connection import message_severity

logger = logging.getLogger("backend.services.servo_thread")
# The loop runs at 10 Hz: a persistent fault (LinuxCNC gone, mapper
# bug) must not write ten identical lines per second.
loop_logger = NonRepeatingLogger("backend.services.servo_thread.loop")

#: A client that cannot take a frame within this time is dropped. One
#: stalled browser (Wi-Fi gone, tab frozen, full TCP buffer) used to
#: block every other client and the whole loop on its send.
SEND_TIMEOUT_S = 1.0


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

    async def _send(self, connection: WebSocket, message: str) -> None:
        try:
            await asyncio.wait_for(connection.send_text(message), SEND_TIMEOUT_S)
        except Exception as e:  # noqa: BLE001 - includes asyncio.TimeoutError
            logger.warning("Dropping WebSocket client (%s): %s", type(e).__name__, e)
            self.disconnect(connection)
            try:
                await asyncio.wait_for(connection.close(code=1011), SEND_TIMEOUT_S)
            except Exception:  # noqa: BLE001 - already broken
                pass

    async def broadcast(self, message: str):
        """Send to every client concurrently, each bounded by ``SEND_TIMEOUT_S``."""
        connections = list(self.active_connections)
        if connections:
            await asyncio.gather(*(self._send(c, message) for c in connections))

    async def close_all(self) -> None:
        """Shutdown: tell every client the server is going away (1001)."""
        connections = list(self.active_connections)
        self.active_connections.clear()
        for connection in connections:
            try:
                await asyncio.wait_for(connection.close(code=1001), SEND_TIMEOUT_S)
            except Exception:  # noqa: BLE001 - best effort
                pass

    def get_initial_state_json(self) -> str:
        """Generates the full state payload for a newly connected client."""
        stat = self.state_service.get_polled_stat()
        history = self.state_service.get_error_history()

        current_dto = ServoThreadStateMapper.from_stat(stat, history)
        full_response = ServoThreadStateMapper.to_response(current_dto)

        envelope = WSEnvelope[ServoThreadStateResponse](type="full_state", data=full_response)
        self._last_broadcast_state = current_dto
        return envelope.model_dump_json(exclude_none=True)

    def get_current_state(self) -> Dict[str, Any]:
        """Return the full ``full_state`` payload as a dict."""
        stat = self.state_service.get_polled_stat()
        history = self.state_service.get_error_history()

        current_dto = ServoThreadStateMapper.from_stat(stat, history)
        full_response = ServoThreadStateMapper.to_response(current_dto)
        return full_response.model_dump(exclude_none=True)

    async def dispatch_inbound(self, websocket: WebSocket, msg: Dict[str, Any]) -> None:
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

        Every ~1 s (every 10th tick) a ``{"type": "heartbeat"}``
        envelope is broadcast even when no state changed. The
        frontend's freeze watchdog (``frontend/src/stores/baseThread.ts``)
        treats a silent socket as a dead one — without the heartbeat
        an idle machine (no deltas) would look frozen to the UI.
        """
        console_logger = get_console_logger()
        tick = 0

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

                        # ``(MSG, ...)`` is an operator message, not a
                        # fault — only real errors are logged/shown as such.
                        severity = message_severity(int(kind))
                        if severity == "info":
                            console_logger.log_response(f"Machine message ({kind}): {text}", level=LogLevel.INFO)
                        else:
                            console_logger.log_response(f"Machine error ({kind}): {text}", level=LogLevel.ERROR)

                        # The envelope type stays ``error`` (it is the
                        # error *channel*); ``data.severity`` carries
                        # the actual classification.
                        payload = json.dumps({
                            "type": "error",
                            "data": LinuxCNCError(
                                kind=int(kind), text=str(text), time=now_iso(), severity=severity,
                            ).model_dump(),
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

                # 4. Heartbeat — one frame per second regardless of
                # deltas, so the client can distinguish "idle machine"
                # from "dead socket".
                tick += 1
                if tick % 10 == 0 and self.active_connections:
                    heartbeat_json = json.dumps({
                        "type": "heartbeat",
                        "data": {"server_time": now_iso()},
                    })
                    await self.broadcast(heartbeat_json)

            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - the loop must keep running
                loop_logger.error("Error in telemetry loop: %s", e)

            # Sleep for 100ms (10Hz refresh rate)
            await asyncio.sleep(0.1)


# Singleton Provider
_SERVICE_INSTANCE = None

def get_servo_thread_service() -> ServoThreadService:
    global _SERVICE_INSTANCE
    if _SERVICE_INSTANCE is None:
        _SERVICE_INSTANCE = ServoThreadService()
    return _SERVICE_INSTANCE