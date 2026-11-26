"""A simulated ACE Pro, as an :class:`.transport.AceTransport`.

Answers the documented methods the way the protocol notes describe:
``busy`` while a feed or unwind runs (``length / speed`` seconds, scaled
by ``time_scale``), a dryer counting down, slots with filament, and the
real unit's quirks — it drops the link after 3 s without a complete
frame, and can be told to lose answers or emit garbage. For tests, and
for working on the UI before the hardware is there.

It also models where each slot's filament tip is (mm past the unit's
outlet, moving with feeds and unwinds), so simulated filament sensors
can trigger: :meth:`SimulatedAce.filament_at`.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any

from .frame import FrameDecoder, _frame

SILENCE_DISCONNECT_S = 3.0


@dataclass
class SimSlot:
    status: str = "ready"
    type: str = "PLA"
    brand: str = "Generic"
    sku: str = ""
    color: tuple[int, int, int] = (255, 255, 255)
    rfid: int = 0


@dataclass
class SimLog:
    """What the host asked for, for assertions."""
    methods: list[str] = field(default_factory=list)
    params: list[dict[str, Any]] = field(default_factory=list)


class SimulatedAce:
    def __init__(self, *, time_scale: float = 1.0, slots: list[SimSlot] | None = None,
                 silence_disconnect_s: float = SILENCE_DISCONNECT_S, firmware: str = "V1.3.84") -> None:
        self.time_scale = time_scale
        self.slots = slots if slots is not None else [SimSlot(), SimSlot(color=(255, 0, 0)), SimSlot(status="empty"),
                                                      SimSlot(type="PETG", color=(0, 0, 255))]
        self.silence_disconnect_s = silence_disconnect_s
        self.firmware = firmware
        self.log = SimLog()
        self.is_open = False
        self.opens = 0
        #: Fault injection
        self.drop_next = 0            # answers to swallow
        self.garbage_before_next = b""  # bytes sent before the next answer
        self.unplugged = False        # open() fails, reads fail
        self.error_methods: dict[str, tuple[int, str]] = {}
        self._decoder = FrameDecoder()
        self._out = bytearray()
        self._busy_until = 0.0
        self._action = ""
        self._dry_until = 0.0
        self._dry: dict[str, Any] = {}
        self.feed_assist: set[int] = set()
        self._last_frame = 0.0
        #: Each slot's filament tip, mm past the outlet (0: parked in the unit).
        self.tip = [0.0] * len(self.slots)
        self._motion: dict[str, Any] | None = None  # slot, sign, speed, length, start, base
        #: A slot whose filament jams after this many mm (tests).
        self.jam_after: dict[int, float] = {}

    # -- the transport side ---------------------------------------------- #

    async def open(self) -> None:
        if self.unplugged:
            raise OSError("no such device")
        self.is_open, self._last_frame = True, time.monotonic()
        self.opens += 1
        self._decoder.reset()
        self._out.clear()

    async def close(self) -> None:
        self.is_open = False

    async def write(self, data: bytes) -> None:
        self._check_link()
        for message in self._decoder.feed(data):
            self._last_frame = time.monotonic()
            self._answer(message)

    async def read(self) -> bytes:
        self._check_link()
        if not self._out:
            await asyncio.sleep(0.005)
            self._check_link()
        data, self._out = bytes(self._out), bytearray()
        return data

    def _check_link(self) -> None:
        if self.unplugged or not self.is_open:
            raise OSError("ACE gone")
        if time.monotonic() - self._last_frame > self.silence_disconnect_s:
            # the real unit resets its USB link after 3 s of silence
            self.is_open = False
            raise OSError("ACE reset the link (silence)")

    # -- the ACE side ----------------------------------------------------- #

    def _now(self) -> float:
        return time.monotonic()

    def _busy(self) -> bool:
        self._advance()
        if self._busy_until and self._now() >= self._busy_until:
            self._busy_until, self._action = 0.0, ""
        return bool(self._busy_until)

    def _start(self, action: str, length: float, speed: float, slot: int = 0) -> None:
        self._advance()
        self._action = action
        self._busy_until = self._now() + (length / speed) * self.time_scale
        self._motion = {"slot": slot, "sign": 1 if action == "feeding" else -1, "speed": speed, "length": length,
                        "start": self._now(), "base": self.tip[slot]}

    def _advance(self, stop: bool = False) -> None:
        """Move the tip of the slot that is feeding / unwinding to now."""
        m = self._motion
        if m is None:
            return
        elapsed = (self._now() - m["start"]) / max(self.time_scale, 1e-9)
        moved = min(m["length"], m["speed"] * elapsed)
        tip = max(0.0, m["base"] + m["sign"] * moved)
        jam = self.jam_after.get(m["slot"])
        if jam is not None and m["sign"] > 0:
            tip = min(tip, jam)
        self.tip[m["slot"]] = tip
        if stop or moved >= m["length"]:
            self._motion = None

    def filament_at(self, distance: float) -> bool:
        """Is any slot's filament at least ``distance`` mm past the outlet
        (a sensor there would see it)?"""
        self._advance()
        return any(t >= distance for t in self.tip)

    def _status(self) -> dict[str, Any]:
        drying = self._dry_until > self._now()
        remain = max(0.0, (self._dry_until - self._now()) / 60 / max(self.time_scale, 1e-9)) if drying else 0
        return {
            "status": "busy" if self._busy() else "ready",
            "action": self._action,
            "dryer_status": {"status": "drying" if drying else "stop", "target_temp": self._dry.get("temp", 0),
                             "duration": self._dry.get("duration", 0), "remain_time": round(remain)},
            "temp": self._dry.get("temp", 25) if drying else 25,
            "enable_rfid": 1,
            "fan_speed": self._dry.get("fan_speed", 0) if drying else 0,
            "feed_assist_count": len(self.feed_assist),
            "cont_assist_time": 0,
            "slots": [{"index": i, "status": s.status, "sku": s.sku, "brand": s.brand, "type": s.type,
                       "color": list(s.color), "rfid": s.rfid} for i, s in enumerate(self.slots)],
        }

    def _result(self, method: str, params: dict[str, Any]) -> tuple[int, str, dict[str, Any] | None]:
        index = int(params.get("index") or 0)
        if method == "get_info":
            return 0, "success", {"id": 0, "slots": len(self.slots), "model": "Anycubic Color Engine Pro",
                                  "firmware": self.firmware, "boot_firmware": "V1.0.1"}
        if method == "get_status":
            return 0, "success", self._status()
        if method == "get_filament_info":
            s = self.slots[index]
            return 0, "success", {"index": index, "sku": s.sku, "brand": s.brand, "type": s.type,
                                  "color": list(s.color), "rfid": s.rfid,
                                  "extruder_temp": {"min": 190, "max": 230}, "hotbed_temp": {"min": 50, "max": 60},
                                  "diameter": 1.75, "total": 330, "current": 0}
        if method in ("feed_filament", "unwind_filament"):
            if self._busy():
                return 1, "busy", None
            if method == "feed_filament" and self.slots[index].status != "ready":
                return 2, "slot empty", None
            self._start("feeding" if method == "feed_filament" else "unwinding",
                        float(params["length"]), float(params["speed"]), index)
            return 0, "success", None
        if method in ("stop_feed_filament", "stop_unwind_filament"):
            self._advance(stop=True)
            self._busy_until, self._action = 0.0, ""
            return 0, "success", None
        if method in ("update_feeding_speed", "update_unwinding_speed"):
            return 0, "success", None
        if method == "start_feed_assist":
            self.feed_assist.add(index)
            return 0, "success", None
        if method == "stop_feed_assist":
            self.feed_assist.discard(index)
            return 0, "", None
        if method == "drying":
            self._dry = dict(params)
            self._dry_until = self._now() + float(params["duration"]) * 60 * self.time_scale
            return 0, "drying", None
        if method == "drying_stop":
            self._dry_until = 0.0
            return 0, "success", None
        if method in ("enable_rfid", "disable_rfid"):
            return 0, "success", None
        return 404, f"unknown method {method}", None

    def _answer(self, message: dict[str, Any]) -> None:
        method = str(message.get("method", ""))
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        self.log.methods.append(method)
        self.log.params.append(dict(params))
        if self.drop_next > 0:
            self.drop_next -= 1
            return
        if method in self.error_methods:
            code, msg = self.error_methods[method]
            result: dict[str, Any] | None = None
        else:
            code, msg, result = self._result(method, params)
        response: dict[str, Any] = {"id": message.get("id"), "code": code, "msg": msg}
        if result is not None:
            response["result"] = result
        self._out += self.garbage_before_next
        self.garbage_before_next = b""
        self._out += _frame(json.dumps(response, separators=(",", ":")).encode())


__all__ = ["SimLog", "SimSlot", "SimulatedAce"]
