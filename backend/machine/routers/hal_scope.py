"""Debug tab: live HAL pin values (1 Hz) and the oscilloscope stream.

* ``POST /api/v1/hal/pins/values`` — current values of the given pins
  (the ones on screen), polled about once a second while visible.
* ``WS /ws/hal-scope`` — fast sampling of up to 16 pins. The client sends

      {"type": "configure", "pins": ["motion.spindle-on", ...], "rate_hz": 200}
      {"type": "stop"}

  and receives ``{"type": "config", "pins": [...], "rate_hz": ...}``
  once per configure, then ``{"type": "samples", "pins": [...],
  "t": [seconds since configure], "v": [[values of pin 0], ...],
  "missed": n}`` blocks about every 50 ms. Bits are sent as 0/1,
  unreadable values as ``null``. Errors: ``{"type": "error", "message"}``.

Routing: ``/ws`` and ``/api/v1/hal`` both go to the machine backend
(``deploy/nginx/linuxcnc-ui-routes.conf``, vite ``DEV_PROXY``).
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from exceptions import BadRequestError
from models.HalModels import HalPinValuesRequest, HalPinValuesResponse
from services.HalScopeService import ScopeSampler, get_hal_scope_service

logger = logging.getLogger("backend.routers.hal_scope")

router = APIRouter(tags=["hal"])

#: Frames waiting for a slow client; beyond this the oldest are dropped
#: (a debug scope must never back up into the sampler or the loop).
_MAX_QUEUED_FRAMES = 40


@router.post(
    "/api/v1/hal/pins/values",
    response_model=HalPinValuesResponse,
    summary="Read the current value of the given HAL pins",
    description="In-process `hal.get_value` per pin — cheap enough for a 1 Hz poll of the pins on screen.",
    operation_id="readHalPinValues",
)
def read_pin_values(request: HalPinValuesRequest) -> HalPinValuesResponse:
    values = get_hal_scope_service().read_values(request.pins)
    read_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return HalPinValuesResponse(values=values, read_at=read_at)


@router.websocket("/ws/hal-scope")
async def hal_scope(websocket: WebSocket) -> None:
    await websocket.accept()
    loop = asyncio.get_running_loop()
    queue: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
    sampler: Optional[ScopeSampler] = None

    def enqueue(frame: Dict[str, Any]) -> None:  # runs on the event loop
        while queue.qsize() >= _MAX_QUEUED_FRAMES:
            queue.get_nowait()
        queue.put_nowait(frame)

    def emit(frame: Dict[str, Any]) -> None:  # runs in the sampler thread
        loop.call_soon_threadsafe(enqueue, frame)

    async def sender() -> None:
        while True:
            frame = await queue.get()
            await websocket.send_text(json.dumps(frame, separators=(",", ":")))

    async def stop_sampler() -> None:
        nonlocal sampler
        if sampler is not None:
            await asyncio.to_thread(sampler.stop)
            sampler = None

    send_task = asyncio.create_task(sender())
    try:
        while True:
            message = await websocket.receive_json()
            kind = message.get("type") if isinstance(message, dict) else None
            if kind == "configure":
                await stop_sampler()
                # Drop frames of the previous configuration.
                while not queue.empty():
                    queue.get_nowait()
                try:
                    sampler = get_hal_scope_service().start_sampler(
                        message.get("pins"), message.get("rate_hz"), emit
                    )
                except BadRequestError as exc:
                    enqueue({"type": "error", "message": str(exc.detail)})
                    continue
                enqueue({"type": "config", "pins": sampler.pins, "rate_hz": sampler.rate_hz})
            elif kind == "stop":
                await stop_sampler()
            else:
                enqueue({"type": "error", "message": f"unknown message type {kind!r}"})
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001 - a debug socket must not take anything down
        logger.warning("HAL scope socket ended: %s", exc)
    finally:
        await stop_sampler()
        send_task.cancel()


__all__ = ["router"]
