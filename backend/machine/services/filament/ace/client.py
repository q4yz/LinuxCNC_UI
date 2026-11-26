"""Talking to an ACE Pro: requests, keep-alive, reconnects.

* **One request in flight.** The ACE has no flow control and may drop
  output when a new frame arrives before it answered; requests queue on a
  lock and each waits for the response with its ``id``.
* **Keep-alive.** The ACE drops the USB link when no complete frame
  arrived for 3 s. While idle the client polls ``get_status`` every
  :data:`KEEPALIVE_S`, which also keeps :attr:`AceClient.status` fresh.
* **Reconnects.** A vanished port, or :data:`MAX_MISSED` keep-alives in a
  row without an answer, closes the link; it is reopened every
  :data:`RECONNECT_S`. Waiting requests fail with :class:`AceUnavailable`.
* **Validation.** Indexes, lengths, speeds and dryer settings are checked
  before anything is sent — a bad command to a machine is worse than an
  exception here.
"""
from __future__ import annotations

import asyncio
import contextlib
import itertools
import logging
import time
from collections.abc import Callable
from typing import Any

from .frame import FrameDecoder, encode_frame
from .models import AceInfo, AceStatus, FilamentInfo
from .transport import AceTransport

logger = logging.getLogger("backend.filament.ace")

#: A request's answer must come within this (s).
REQUEST_TIMEOUT_S = 2.0
#: Idle poll (the ACE drops the link after 3 s without a frame).
KEEPALIVE_S = 1.0
#: Keep-alives in a row without an answer before the link is reopened.
MAX_MISSED = 3
RECONNECT_S = 2.0

# Limits — from the protocol notes and the drivers' defaults; widen only
# after checking on a real unit.
MAX_LENGTH_MM = 2000.0
MAX_SPEED_MM_S = 80.0
MAX_DRY_TEMP_C = 55.0
MAX_DRY_MIN = 240
UNWIND_MODES = (0, 1)  # 0 normal, 1 enhanced
DEFAULT_DRY_FAN_RPM = 7000


class AceError(RuntimeError):
    """The ACE answered with an error code."""

    def __init__(self, method: str, code: int, msg: str) -> None:
        super().__init__(f"ACE {method}: error {code} ({msg})")
        self.method, self.code, self.msg = method, code, msg


class AceTimeout(TimeoutError):
    """No answer in time."""


class AceUnavailable(ConnectionError):
    """Not connected (port missing, ACE restarting)."""


def _check(condition: bool, what: str) -> None:
    if not condition:
        raise ValueError(what)


class AceClient:
    def __init__(
        self,
        transport: AceTransport,
        *,
        request_timeout: float = REQUEST_TIMEOUT_S,
        keepalive_s: float = KEEPALIVE_S,
        reconnect_s: float = RECONNECT_S,
        on_status: Callable[[AceStatus], None] | None = None,
        on_connection: Callable[[bool], None] | None = None,
    ) -> None:
        self._transport = transport
        self._request_timeout = request_timeout
        self._keepalive_s = keepalive_s
        self._reconnect_s = reconnect_s
        self._on_status = on_status
        self._on_connection = on_connection
        self._decoder = FrameDecoder()
        self._ids = itertools.count(1)
        self._lock = asyncio.Lock()
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._task: asyncio.Task[None] | None = None
        self._last_sent = 0.0
        self._connected = asyncio.Event()
        #: The port is open for requests (``connected`` follows once info and status came back).
        self._link = False
        self.info: AceInfo | None = None
        self.status: AceStatus | None = None
        self.last_error = ""

    # -- lifecycle ------------------------------------------------------- #

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._run(), name="ace-client")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await self._disconnect("stopped")

    async def wait_connected(self, timeout: float) -> bool:
        try:
            await asyncio.wait_for(self._connected.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def _run(self) -> None:
        while True:
            try:
                await self._transport.open()
                self._decoder.reset()
                reader = asyncio.create_task(self._read_loop())
                try:
                    self._link = True
                    self.info = AceInfo.parse(await self.request("get_info"))
                    logger.info("ACE connected: %s, firmware %s", self.info.model, self.info.firmware)
                    await self.get_status()  # the slots at once, not after the first keep-alive
                    self._set_connected(True)
                    await self._keepalive_loop(reader)
                finally:
                    reader.cancel()
                    with contextlib.suppress(asyncio.CancelledError, OSError):
                        await reader
            except asyncio.CancelledError:
                raise
            except (OSError, AceTimeout, AceUnavailable, AceError) as exc:
                self.last_error = str(exc) or type(exc).__name__
                logger.warning("ACE link lost: %s", self.last_error)
            await self._disconnect(self.last_error or "disconnected")
            await asyncio.sleep(self._reconnect_s)

    def _set_connected(self, connected: bool) -> None:
        was = self._connected.is_set()
        if connected:
            self._connected.set()
        else:
            self._connected.clear()
        if was != connected and self._on_connection is not None:
            self._on_connection(connected)

    async def _disconnect(self, why: str) -> None:
        self._link = False
        self._set_connected(False)
        for future in self._pending.values():
            if not future.done():
                future.set_exception(AceUnavailable(why))
        self._pending.clear()
        with contextlib.suppress(OSError):
            await self._transport.close()

    async def _read_loop(self) -> None:
        while True:
            data = await self._transport.read()  # OSError ends the link
            if not data:
                continue
            for message in self._decoder.feed(data):
                request_id = message.get("id")
                future = self._pending.get(request_id) if isinstance(request_id, int) else None
                if future is not None and not future.done():
                    future.set_result(message)

    async def _keepalive_loop(self, reader: asyncio.Task[None]) -> None:
        missed = 0
        while True:
            await asyncio.sleep(min(0.25, self._keepalive_s / 4))
            if reader.done():
                reader.result()  # re-raise the read error
                raise AceUnavailable("reader stopped")
            if time.monotonic() - self._last_sent < self._keepalive_s or self._lock.locked():
                continue
            try:
                await self.get_status()
                missed = 0
            except AceTimeout:
                missed += 1
                if missed >= MAX_MISSED:
                    raise AceTimeout(f"{missed} keep-alives unanswered") from None

    # -- requests ---------------------------------------------------------- #

    async def request(self, method: str, params: dict[str, Any] | None = None,
                      timeout: float | None = None) -> dict[str, Any]:
        """Send one request, return its ``result`` (``{}`` when there is none)."""
        message: dict[str, Any] = {"method": method}
        if params:
            message["params"] = params
        async with self._lock:
            if not self._link:
                raise AceUnavailable(self.last_error or "not connected")
            request_id = next(self._ids)
            frame = encode_frame({"id": request_id, **message})
            future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
            self._pending[request_id] = future
            try:
                await self._transport.write(frame)
                self._last_sent = time.monotonic()
                try:
                    response = await asyncio.wait_for(future, timeout or self._request_timeout)
                except asyncio.TimeoutError:
                    raise AceTimeout(f"ACE {method}: no answer") from None
            finally:
                self._pending.pop(request_id, None)
        code = response.get("code", 0)
        if code not in (0, None):
            raise AceError(method, int(code), str(response.get("msg", "")))
        result = response.get("result")
        return result if isinstance(result, dict) else {}

    def _slot(self, index: int) -> int:
        slots = self.info.slots if self.info else 4
        _check(isinstance(index, int) and 0 <= index < slots, f"slot must be 0..{slots - 1}, got {index!r}")
        return index

    @staticmethod
    def _length(length: float) -> float:
        _check(0 < length <= MAX_LENGTH_MM, f"length must be 0 < l <= {MAX_LENGTH_MM} mm, got {length!r}")
        return length

    @staticmethod
    def _speed(speed: float) -> float:
        _check(0 < speed <= MAX_SPEED_MM_S, f"speed must be 0 < v <= {MAX_SPEED_MM_S} mm/s, got {speed!r}")
        return speed

    # -- the ACE's methods ----------------------------------------------- #

    async def get_info(self) -> AceInfo:
        self.info = AceInfo.parse(await self.request("get_info"))
        return self.info

    async def get_status(self) -> AceStatus:
        status = AceStatus.parse(await self.request("get_status"))
        self.status = status
        if self._on_status is not None:
            self._on_status(status)
        return status

    async def get_filament_info(self, index: int) -> FilamentInfo:
        return FilamentInfo.parse(await self.request("get_filament_info", {"index": self._slot(index)}))

    async def feed(self, index: int, length: float, speed: float) -> None:
        """Push ``length`` mm of slot ``index`` towards the printer at ``speed`` mm/s."""
        await self.request("feed_filament", {"index": self._slot(index), "length": self._length(length),
                                             "speed": self._speed(speed)})

    async def update_feed_speed(self, index: int, speed: float) -> None:
        await self.request("update_feeding_speed", {"index": self._slot(index), "speed": self._speed(speed)})

    async def stop_feed(self, index: int) -> None:
        await self.request("stop_feed_filament", {"index": self._slot(index)})

    async def unwind(self, index: int, length: float, speed: float, mode: int = 0) -> None:
        """Pull ``length`` mm of slot ``index`` back (mode 0 normal, 1 enhanced)."""
        _check(mode in UNWIND_MODES, f"mode must be one of {UNWIND_MODES}, got {mode!r}")
        await self.request("unwind_filament", {"index": self._slot(index), "length": self._length(length),
                                               "speed": self._speed(speed), "mode": mode})

    async def update_unwind_speed(self, index: int, speed: float) -> None:
        await self.request("update_unwinding_speed", {"index": self._slot(index), "speed": self._speed(speed)})

    async def stop_unwind(self, index: int) -> None:
        await self.request("stop_unwind_filament", {"index": self._slot(index)})

    async def start_feed_assist(self, index: int) -> None:
        await self.request("start_feed_assist", {"index": self._slot(index)})

    async def stop_feed_assist(self, index: int) -> None:
        await self.request("stop_feed_assist", {"index": self._slot(index)})

    async def start_drying(self, temp_c: float, duration_min: int, fan_rpm: int = DEFAULT_DRY_FAN_RPM) -> None:
        _check(0 < temp_c <= MAX_DRY_TEMP_C, f"drying temperature must be 0 < t <= {MAX_DRY_TEMP_C} °C")
        _check(isinstance(duration_min, int) and 1 <= duration_min <= MAX_DRY_MIN,
               f"drying time must be 1..{MAX_DRY_MIN} min")
        await self.request("drying", {"temp": temp_c, "fan_speed": fan_rpm, "duration": duration_min})

    async def stop_drying(self) -> None:
        await self.request("drying_stop")

    async def set_rfid(self, enabled: bool) -> None:
        await self.request("enable_rfid" if enabled else "disable_rfid")

    async def wait_ready(self, timeout: float, poll_s: float = 0.25) -> AceStatus:
        """Poll until the ACE is no longer busy (a feed or unwind finished)."""
        deadline = time.monotonic() + timeout
        while True:
            status = await self.get_status()
            if status.ready:
                return status
            if time.monotonic() >= deadline:
                raise AceTimeout(f"ACE still {status.action or status.status} after {timeout:.0f} s")
            await asyncio.sleep(poll_s)


__all__ = ["AceClient", "AceError", "AceTimeout", "AceUnavailable"]
