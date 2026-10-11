"""Robustness of the machine backend: telemetry fan-out and shutdown.

* a stalled WebSocket client is dropped instead of blocking every other
  client (and the telemetry loop) on its send;
* the HAL component is exited on shutdown so LinuxCNC's ``unloadusr``
  does not wait for the process to disappear.
"""
from __future__ import annotations

import asyncio
from typing import List

import pytest

import services.ServoThreadService as servo_mod
from services.ServoThreadService import ServoThreadService


class _FakeSocket:
    def __init__(self, *, stall: bool = False, broken: bool = False) -> None:
        self.stall = stall
        self.broken = broken
        self.sent: List[str] = []
        self.closed_with: List[int] = []

    async def send_text(self, message: str) -> None:
        if self.broken:
            raise RuntimeError("connection reset")
        if self.stall:
            await asyncio.sleep(3600)  # full TCP buffer / frozen tab
        self.sent.append(message)

    async def close(self, code: int = 1000) -> None:
        self.closed_with.append(code)


@pytest.fixture()
def service(monkeypatch):
    monkeypatch.setattr(servo_mod, "SEND_TIMEOUT_S", 0.05)
    svc = ServoThreadService.__new__(ServoThreadService)
    svc.active_connections = []
    svc._last_broadcast_state = None
    return svc


def test_a_stalled_client_is_dropped_and_others_still_get_the_frame(service):
    good, stalled, broken = _FakeSocket(), _FakeSocket(stall=True), _FakeSocket(broken=True)
    service.active_connections = [stalled, good, broken]

    async def run():
        await asyncio.wait_for(service.broadcast("frame-1"), timeout=2)
        await asyncio.wait_for(service.broadcast("frame-2"), timeout=2)

    asyncio.run(run())

    assert good.sent == ["frame-1", "frame-2"]
    assert service.active_connections == [good]
    assert stalled.closed_with == [1011]
    assert broken.closed_with == [1011]


def test_close_all_says_going_away(service):
    a, b = _FakeSocket(), _FakeSocket()
    service.active_connections = [a, b]
    asyncio.run(service.close_all())
    assert a.closed_with == [1001] and b.closed_with == [1001]
    assert service.active_connections == []


def test_hal_component_exit_is_idempotent(monkeypatch):
    from dtos.pins.HalPin import HalPin

    exits: List[int] = []

    class _Comp:
        def exit(self) -> None:
            exits.append(1)

    monkeypatch.setattr(HalPin, "_comp_instance", _Comp())
    HalPin.shutdown_component()
    HalPin.shutdown_component()
    assert exits == [1]
    assert HalPin._comp_instance is None


def test_health_reports_whether_linuxcnc_status_is_readable(monkeypatch):
    import main

    class _Stat:
        def __init__(self, fail: bool) -> None:
            self.fail = fail

        def poll(self) -> None:
            if self.fail:
                raise RuntimeError("emcStatusBuffer invalid")

    monkeypatch.setattr(main, "get_stat_channel", lambda: _Stat(fail=False))
    assert asyncio.run(main.machine_health())["linuxcnc_connected"] is True

    monkeypatch.setattr(main, "get_stat_channel", lambda: _Stat(fail=True))
    assert asyncio.run(main.machine_health())["linuxcnc_connected"] is False

    monkeypatch.setattr(main, "get_stat_channel", lambda: None)
    body = asyncio.run(main.machine_health())
    assert body["linuxcnc_connected"] is False
    assert body["status"] == "ok"
