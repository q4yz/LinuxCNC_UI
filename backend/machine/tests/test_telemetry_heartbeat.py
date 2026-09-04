"""Tests for the telemetry WebSocket heartbeat.

``ServoThreadService.telemetry_loop`` only broadcasts ``delta``
frames when the machine state actually changes, so a completely
idle machine can stay silent for a long time. The frontend freeze
watchdog (``frontend/src/stores/baseThread.ts``) needs at least one
frame per second to tell "idle machine" from "dead socket" — the
loop therefore emits a ``{"type": "heartbeat"}`` envelope every
~1 s (every 10th 100 ms tick) regardless of deltas.
"""

from __future__ import annotations

from typing import Any

import asyncio
import json
from unittest.mock import patch


def _parsed(captured: list[str]) -> list[dict[str, Any]]:
    """Parse every captured broadcast payload, skipping junk."""
    out: list[dict[str, Any]] = []
    for raw in captured:
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return out


def _drive_loop(ticks_of_sleep: int) -> list[str]:
    """Run ``telemetry_loop`` long enough for the requested number of
    event-loop yields and return every broadcast payload (raw JSON).
    """
    from services.ServoThreadService import ServoThreadService

    async def drive():
        svc = ServoThreadService()
        captured: list[str] = []

        async def fake_broadcast(message: str) -> None:
            captured.append(message)

        real_sleep = asyncio.sleep

        async def fake_sleep(_seconds: float) -> None:
            # Use the real ``sleep`` via closure so the patched
            # ``asyncio.sleep`` does not recurse into itself.
            await real_sleep(0)

        svc.active_connections = [object()]
        svc.broadcast = fake_broadcast

        with patch.object(asyncio, "sleep", side_effect=fake_sleep):
            task = asyncio.create_task(svc.telemetry_loop())
            for _ in range(ticks_of_sleep):
                await real_sleep(0)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        return captured

    return asyncio.run(drive())


def test_telemetry_loop_broadcasts_heartbeat_when_idle():
    """No errors pushed, machine idle: the loop must still emit
    ``{"type": "heartbeat"}`` envelopes so the client sees traffic
    and never mistakes an idle machine for a dead socket.
    """
    heartbeats = [
        msg for msg in _parsed(_drive_loop(120)) if msg.get("type") == "heartbeat"
    ]
    assert heartbeats, "telemetry_loop must broadcast heartbeats even without deltas"
    payload = heartbeats[-1]["data"]
    assert "server_time" in payload, "heartbeat must carry a server_time stamp"


def test_heartbeat_cadence_is_one_per_second():
    """The heartbeat fires every 10th tick (10 Hz loop → ~1 Hz)."""
    heartbeats = [
        msg for msg in _parsed(_drive_loop(120)) if msg.get("type") == "heartbeat"
    ]
    # 120 driver yields ≈ 60 loop iterations (two awaits each) →
    # at least 5 heartbeats expected from the modulo-10 cadence.
    assert len(heartbeats) >= 5, (
        "expected roughly one heartbeat per 10 loop ticks "
        f"(got {len(heartbeats)})"
    )


def test_heartbeat_skipped_without_clients():
    """With no connected clients the loop must not bother building
    heartbeat payloads (broadcast is a no-op anyway).
    """
    from services.ServoThreadService import ServoThreadService

    async def drive():
        svc = ServoThreadService()
        captured: list[str] = []

        async def fake_broadcast(message: str) -> None:
            captured.append(message)

        real_sleep = asyncio.sleep

        async def fake_sleep(_seconds: float) -> None:
            await real_sleep(0)

        svc.active_connections = []
        svc.broadcast = fake_broadcast

        with patch.object(asyncio, "sleep", side_effect=fake_sleep):
            task = asyncio.create_task(svc.telemetry_loop())
            for _ in range(120):
                await real_sleep(0)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        return captured

    heartbeats = [msg for msg in _parsed(asyncio.run(drive())) if msg.get("type") == "heartbeat"]
    assert not heartbeats, "no heartbeat without active connections"
