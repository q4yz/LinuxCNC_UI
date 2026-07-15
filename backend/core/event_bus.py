"""
Asynchronous publish/subscribe EventBus for inter-module communication.

This module provides a lightweight event bus that lets backend modules
(e.g. Temperature, VFD, Spindle) communicate without importing each
other directly. Modules publish events to topics and subscribe to topics
of interest. Subscribers are async callables invoked concurrently.

Two guarantees are enforced:

1.  **Payload immutability.** Every :meth:`EventBus.publish` call
    re-instantiates a fresh Pydantic model from
    ``payload.model_dump()`` before fanning out, so a buggy subscriber
    mutating the payload cannot affect other subscribers. This is the
    rule from ``MODULE_SYSTEM_ROADMAP.md`` § 12 Gotcha #3.

2.  **State-topic rate-limiting.** Topics prefixed with ``"state."``
    are deduplicated: if the incoming payload equals the last value
    cached for that topic, the publish call becomes a no-op. This keeps
    high-frequency publishers (encoder, temperature sampler) from
    flooding downstream subscribers.

The two rules are deliberately orthogonal: ``TelemetryBus`` (see
:mod:`core.telemetry.bus`) gets a *by-reference* path explicitly
opted-in by its consumers, because the 100 Hz telemetry stream cannot
afford the cost of re-instantiating Pydantic models on every tick.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Callable, Dict, List

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class EventBus:
    """In-process asynchronous publish/subscribe bus.

    The bus keeps a mapping of ``topic -> list[callback]`` and dispatches
    payloads to all registered subscribers concurrently using
    :func:`asyncio.gather`. A single failing subscriber cannot take down
    the bus because each invocation is wrapped in :meth:`_safe_invoke`.

    Topics prefixed with ``"state."`` are deduplicated: if the incoming
    payload is equal to the last value published on that topic, the
    publish call becomes a no-op. This is the rate-limiting mechanism
    referenced in ``MODULE_SYSTEM_ROADMAP.md`` § 12 Gotcha #3 (state
    caching).
    """

    def __init__(self) -> None:
        # topic -> list of async callbacks
        self._subscribers: Dict[str, List[Callable]] = defaultdict(list)

        # Last known payload per topic; used to skip redundant updates
        # on "state." topics so noisy modules don't flood the bus.
        self._state_cache: Dict[str, Any] = {}

    def subscribe(self, topic: str, callback: Callable) -> None:
        """Register an async callback for a specific topic.

        Args:
            topic: The topic name to subscribe to (e.g. ``"vfd.set_freq"``).
            callback: An async callable invoked as
                ``await callback(topic, payload)`` on each publish.
        """
        self._subscribers[topic].append(callback)
        logger.debug("Subscribed to topic: %s", topic)

    def unsubscribe(self, topic: str, callback: Callable) -> bool:
        """Remove a previously registered callback.

        Args:
            topic: The topic name the callback was registered under.
            callback: The exact callable reference to remove.

        Returns:
            True if the callback was found and removed, False otherwise.
        """
        if topic not in self._subscribers:
            return False
        try:
            self._subscribers[topic].remove(callback)
            return True
        except ValueError:
            return False

    async def publish(self, topic: str, payload: Any) -> None:
        """Publish an event to all subscribers of ``topic``.

        Three rules apply, in order:

        1.  **State-topic rate-limit.** For topics prefixed with
            ``"state."``, if the incoming payload equals the last cached
            payload, the call is a no-op (rate-limit).
        2.  **Payload immutability.** If ``payload`` is a Pydantic
            :class:`BaseModel`, every subscriber receives a *fresh copy*
            re-instantiated via ``type(payload).model_validate(payload.model_dump())``.
            A subscriber mutating its copy cannot affect any other
            subscriber or the publisher.
        3.  **Concurrent fan-out.** Subscribers are invoked
            concurrently via :func:`asyncio.gather`; one failing
            subscriber is logged but does not block the others.

        Args:
            topic: The topic name to publish to.
            payload: An arbitrary value. Pydantic models are deep-copied
                before delivery; plain dicts/lists/scalars are passed
                through by reference (this bus does not clone them).
        """
        # 1. Rate-limit / state-cache: skip redundant state.* updates.
        if topic.startswith("state."):
            if self._state_cache.get(topic) == payload:
                return
            self._state_cache[topic] = payload

        callbacks = self._subscribers.get(topic)
        if not callbacks:
            return

        # Give every subscriber its own freshly-copied payload so a
        # subscriber mutating its copy cannot leak into the publisher's
        # copy or any other subscriber's copy.
        tasks = [
            self._safe_invoke(cb, topic, self._copy_payload(payload))
            for cb in callbacks
        ]
        await asyncio.gather(*tasks)

    @staticmethod
    def _copy_payload(payload: Any) -> Any:
        """Return an immutable-friendly copy of ``payload``.

        Pydantic v2 ``BaseModel`` instances are deep-copied via
        :meth:`BaseModel.model_copy` so the new object is fully
        independent — including nested lists/dicts/models. A subscriber
        mutating any field cannot leak into the publisher or any other
        subscriber.

        Plain dicts/lists/scalars are returned by reference because
        deep-copying arbitrary JSON would surprise perf-sensitive
        modules (see the TelemetryBus sibling for the by-reference
        escape hatch).
        """
        if isinstance(payload, BaseModel):
            return payload.model_copy(deep=True)
        return payload

    async def _safe_invoke(
        self, callback: Callable, topic: str, payload: Any
    ) -> None:
        """Invoke a single subscriber without letting exceptions escape.

        Wraps each callback so that a buggy module cannot crash the bus
        or interrupt delivery to other subscribers on the same topic.
        """
        try:
            await callback(topic, payload)
        except Exception as exc:  # noqa: BLE001 - we explicitly want to swallow all errors here
            logger.error(
                "Subscriber error on topic '%s': %s", topic, exc, exc_info=True
            )

    def clear_cache(self) -> None:
        """Reset the state-topic cache.

        Useful in tests or when a module reconnects and wants the next
        publish to be delivered regardless of equality with the prior
        payload.
        """
        self._state_cache.clear()


# Singleton instance for the core system.
# Modules should ``from core.event_bus import bus`` and call
# ``bus.subscribe(...)`` / ``await bus.publish(...)``.
bus = EventBus()


__all__ = ["EventBus", "bus"]