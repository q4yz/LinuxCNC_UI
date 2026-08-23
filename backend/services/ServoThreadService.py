import asyncio
import json
import logging
from typing import List, Optional

from fastapi import WebSocket

from hardware import get_machine_stat, get_machine_error
from hardware.Connection import read_error_history
from mapper.ServoThreadStateMapper import ServoThreadStateMapper
from models.ServoThreadStateResponse import WSEnvelope, ServoThreadStateResponse
from dtos.ServoThreadState import ServoThreadStateDTO
from services.console_logger import LogLevel, get_console_logger

logger = logging.getLogger("backend.services.servo_thread")


class ServoThreadService:
    """Manages WebSocket telemetry broadcasting and inbound command dispatching."""

    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self._last_broadcast_state: Optional[ServoThreadStateDTO] = None

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket Client connected. Total clients: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"WebSocket Client disconnected. Total clients: {len(self.active_connections)}")

    async def broadcast(self, message: str):
        # Iterate over a copy of the list to allow safe removal if a connection drops
        for connection in list(self.active_connections):
            try:
                await connection.send_text(message)
            except Exception as e:
                logger.error(f"Error broadcasting to client: {e}")
                self.disconnect(connection)

    def get_initial_state_json(self) -> str:
        """Generates the full state payload for a newly connected client."""
        machine_stat = get_machine_stat()
        current_dto = ServoThreadStateMapper.from_stat(machine_stat, read_error_history())
        full_response = ServoThreadStateMapper.to_response(current_dto)

        envelope = WSEnvelope[ServoThreadStateResponse](
            type="full_state",
            data=full_response
        )
        # Update the tracker so the delta loop knows the baseline
        self._last_broadcast_state = current_dto
        return envelope.model_dump_json(exclude_none=True)

    async def dispatch_inbound(self, websocket: WebSocket, msg: dict) -> None:
        """Route a JSON command received over the telemetry socket."""
        mtype = msg.get("type")

        if mtype == "jog_keepalive":
            from modules.axis.services.jog_service import jog_keepalive
            axes = msg.get("axes") or []
            if not isinstance(axes, list):
                logger.warning("jog_keepalive: 'axes' must be a list, got %r", type(axes))
                return
            jog_keepalive([int(a) for a in axes])
            return

        if mtype == "jog_axis":
            from modules.axis.services.jog_service import jog_axis
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
            from modules.axis.services.jog_service import jog_stop
            axes = msg.get("axes") or []
            if not isinstance(axes, list):
                logger.warning("jog_stop: 'axes' must be a list, got %r", type(axes))
                return
            jog_stop([int(a) for a in axes])
            return

        logger.debug("unknown WS message type: %r", mtype)

    async def telemetry_loop(self):
        """
        Background loop that continuously polls the CNC machine at 10Hz
        and broadcasts the state diff to all connected WebSockets.
        """
        console_logger = get_console_logger()

        while True:
            try:
                machine_stat = get_machine_stat()
                machine_error = get_machine_error()

                # Handle offline / disconnected state
                if machine_stat is None or machine_error is None:
                    if self.active_connections:
                        current_dto = ServoThreadStateMapper.from_stat(None, read_error_history())
                        diff_resp = ServoThreadStateMapper.get_diff_response(current_dto, self._last_broadcast_state)

                        delta_dict = diff_resp.model_dump(exclude_none=True)
                        if delta_dict:
                            await self.broadcast(json.dumps({"type": "delta", "data": delta_dict}))
                            self._last_broadcast_state = current_dto
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

                if error and self.active_connections:
                    kind, text = error
                    console_logger.log_response(
                        f"Machine error ({kind}): {text}",
                        level=LogLevel.ERROR,
                    )

                current_dto = ServoThreadStateMapper.from_stat(machine_stat, read_error_history())
                diff_resp = ServoThreadStateMapper.get_diff_response(current_dto, self._last_broadcast_state)

                if diff_resp.model_dump(exclude_none=True) and self.active_connections:
                    envelope = WSEnvelope[ServoThreadStateResponse](type="delta", data=diff_resp)
                    payload_json = envelope.model_dump_json(exclude_none=True)

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