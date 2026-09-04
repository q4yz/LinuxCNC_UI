"""Tests for the EventBus payload-immutability contract."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel

from core.event_bus import EventBus


class _Sample(BaseModel):
    name: str
    counters: list


def test_payload_mutation_in_one_subscriber_does_not_affect_another():
    """A subscriber mutating its copy must not affect any other subscriber."""
    bus = EventBus()
    seen: list = []

    async def evil(topic, payload):
        # Mutate both the top-level field and a nested list. If the bus
        # were passing the same object to every subscriber, ``benign``
        # would see the mutations.
        payload.name = "MUTATED"
        payload.counters.append(99)
        seen.append(("evil", payload.name, list(payload.counters)))

    async def benign(topic, payload):
        seen.append(("benign", payload.name, list(payload.counters)))

    bus.subscribe("module.demo.event", evil)
    bus.subscribe("module.demo.event", benign)

    asyncio.run(
        bus.publish(
            "module.demo.event",
            _Sample(name="original", counters=[1, 2, 3]),
        )
    )

    assert seen == [
        ("evil", "MUTATED", [1, 2, 3, 99]),
        ("benign", "original", [1, 2, 3]),
    ]


def test_state_topic_dedup_suppresses_repeated_payloads():
    """``state.*`` topics drop the second equal payload."""
    bus = EventBus()
    delivered: list = []

    async def cb(topic, payload):
        delivered.append(payload)

    bus.subscribe("state.demo", cb)
    asyncio.run(bus.publish("state.demo", {"v": 1}))
    asyncio.run(bus.publish("state.demo", {"v": 1}))
    asyncio.run(bus.publish("state.demo", {"v": 2}))

    assert delivered == [{"v": 1}, {"v": 2}]


def test_non_state_topic_does_not_dedup():
    """``module.<id>.<event>`` topics do not dedup."""
    bus = EventBus()
    delivered: list = []

    async def cb(topic, payload):
        delivered.append(payload)

    bus.subscribe("module.demo.event", cb)
    asyncio.run(bus.publish("module.demo.event", "hi"))
    asyncio.run(bus.publish("module.demo.event", "hi"))

    assert delivered == ["hi", "hi"]


def test_subscribe_unsubscribe_roundtrip():
    bus = EventBus()

    async def cb(topic, payload):
        return None

    bus.subscribe("t", cb)
    assert bus.unsubscribe("t", cb) is True
    # Second unsubscribe returns False because the callback is gone.
    assert bus.unsubscribe("t", cb) is False