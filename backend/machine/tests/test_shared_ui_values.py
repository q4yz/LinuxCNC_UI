"""Shared UI values over the telemetry socket (#128)."""
from __future__ import annotations

import asyncio
import json

from core.auth import GUEST, LOCAL_ADMIN
from services.machine.SharedUiValues import MAX_KEYS, SharedUiValues


def test_store_validates_key_and_value():
    values = SharedUiValues()
    assert values.set("jog.speed", 12.5) == ("jog.speed", 12.5)
    assert values.set("bad key!", 1) is None
    assert values.set("", 1) is None
    assert values.set(3, 1) is None
    assert values.set("x", float("nan")) is None
    assert values.set("x", {"nested": 1}) is None
    assert values.set("x", "a" * 1000) is None
    assert values.snapshot() == {"jog.speed": 12.5}


def test_store_is_bounded_but_existing_keys_update():
    values = SharedUiValues()
    for i in range(MAX_KEYS):
        assert values.set(f"k{i}", i) is not None
    assert values.set("one.more", 1) is None
    assert values.set("k0", 99) == ("k0", 99)


def test_ui_value_is_broadcast_to_every_client():
    from services.machine.ServoThreadService import ServoThreadService

    svc = ServoThreadService()
    svc.shared_values = SharedUiValues()
    sent: list[str] = []

    async def fake_broadcast(message: str) -> None:
        sent.append(message)

    svc.broadcast = fake_broadcast
    asyncio.run(svc.dispatch_inbound(None, {"type": "ui_value", "key": "jog.speed", "value": 25}, LOCAL_ADMIN))
    asyncio.run(svc.dispatch_inbound(None, {"type": "ui_value", "key": "no spaces", "value": 1}, LOCAL_ADMIN))
    # a viewer may watch, not move the sliders (#131)
    asyncio.run(svc.dispatch_inbound(None, {"type": "ui_value", "key": "jog.speed", "value": 99}, GUEST))
    assert [json.loads(m) for m in sent] == [{"type": "ui_value", "data": {"key": "jog.speed", "value": 25}}]
    # a client connecting later gets the whole set
    assert json.loads(svc.get_shared_values_json()) == {"type": "ui_values", "data": {"jog.speed": 25}}


def test_a_viewer_cannot_jog_but_can_stop_a_jog(monkeypatch):
    from services.machine.ServoThreadService import ServoThreadService

    svc = ServoThreadService()
    handled: list[str] = []

    async def fake_axis(msg):
        handled.append(msg["type"])
        return True

    monkeypatch.setattr(svc.axis_service, "dispatch_inbound", fake_axis)
    for kind in ("jog_axis", "jog_keepalive", "jog_stop"):
        asyncio.run(svc.dispatch_inbound(None, {"type": kind}, GUEST))
    assert handled == ["jog_stop"]
    asyncio.run(svc.dispatch_inbound(None, {"type": "jog_axis"}, LOCAL_ADMIN))
    assert handled == ["jog_stop", "jog_axis"]
