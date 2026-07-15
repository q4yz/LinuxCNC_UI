"""
Asynchronous publish/subscribe EventBus for inter-module communication.

This module provides a lightweight event bus that lets backend modules
(e.g. Temperature, VFD, Spindle) communicate without importing each
other directly. Modules publish events to topics and subscribe to topics
of interest. Subscribers are async callables invoked concurrently.

To prevent high-frequency publishers (e.g. encoder or temperature
samplers) from causing telemetry back-pressure, the bus optionally
deduplicates state topics by skipping payloads whose value is unchanged
from the most recently published payload on that topic.
"""

import asyncio
import logging
from collections import defaultdict
from typing import Any, Callable, Dict, List

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
    referenced in the issue (state caching).
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
        logger.debug(f"Subscribed to topic: {topic}")

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

        For topics prefixed with ``"state."``, the payload is compared
        against the last value cached for the topic and the publish is
        skipped when they are equal. This is a cheap rate-limiting
        mechanism that prevents high-frequency modules from causing
        redundant work downstream.

        Subscribers are invoked concurrently; one failing subscriber is
        logged but does not prevent the others from running.

        Args:
            topic: The topic name to publish to.
            payload: An arbitrary JSON-serialisable value to forward.
        """
        # Rate-limit / state-cache: skip redundant state.* updates.
        if topic.startswith("state."):
            if self._state_cache.get(topic) == payload:
                return
            self._state_cache[topic] = payload

        callbacks = self._subscribers.get(topic)
        if not callbacks:
            return

        tasks = [self._safe_invoke(cb, topic, payload) for cb in callbacks]
        await asyncio.gather(*tasks)

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
                f"Subscriber error on topic '{topic}': {exc}", exc_info=True
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