"""
TelemetryBus: high-frequency pub/sub for machine telemetry.

``TelemetryBus`` exists alongside :class:`core.event_bus.EventBus` but
follows the opposite contract: payloads are delivered **by reference**
(no Pydantic copy) so consumers can subscribe to 100 Hz telemetry
without paying for a model re-instantiation on every tick.

The two buses are deliberately split:

* :class:`core.event_bus.EventBus` — module-to-module commands and
  slow state transitions. Payload immutability is mandatory because
  modules are independent codebases we don't control.
* :class:`core.telemetry.bus.TelemetryBus` — single-source-of-truth
  telemetry stream produced by the WebSocket broadcast task. Subscribers
  are part of the core platform and trust the producer to hand out
  fresh objects on every publish.

Phase 2c only adds the *shell*: the existing
``routers/websocket.py`` transport is untouched, so the bus is wired
in but the WebSocket task does not publish to it yet. Phase 4 will
fold the broadcast loop into this bus.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Callable, Dict, List

logger = logging.getLogger(__name__)


class TelemetryBus:
    """In-process pub/sub bus for high-frequency telemetry.

    Subscribers are async callables invoked as
    ``await callback(topic, payload)``. Payloads are delivered **by
    reference** — the bus never copies or freezes them — so consumers
    must treat the payload as read-only or copy it themselves before
    storing it. This trade-off is documented in
    ``MODULE_SYSTEM_ROADMAP.md`` § 12 Gotcha #3.
    """

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[Callable]] = defaultdict(list)

    def subscribe(self, topic: str, callback: Callable) -> None:
        """Register an async callback for ``topic``.

        Args:
            topic: Telemetry topic (e.g. ``"full_state"``, ``"delta"``).
            callback: Async callable invoked as
                ``await callback(topic, payload)`` on each publish.
        """
        self._subscribers[topic].append(callback)
        logger.debug("TelemetryBus: subscribed to %s", topic)

    def unsubscribe(self, topic: str, callback: Callable) -> bool:
        """Remove a previously registered callback. Returns True if removed."""
        if topic not in self._subscribers:
            return False
        try:
            self._subscribers[topic].remove(callback)
            return True
        except ValueError:
            return False

    async def publish(self, topic: str, payload: Any) -> None:
        """Publish ``payload`` to all subscribers of ``topic``.

        Args:
            topic: Telemetry topic.
            payload: Object delivered **by reference**. Subscribers
                must not mutate it.
        """
        callbacks = self._subscribers.get(topic)
        if not callbacks:
            return

        async def _safe(cb: Callable) -> None:
            try:
                await cb(topic, payload)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "TelemetryBus subscriber error on %s: %s",
                    topic,
                    exc,
                    exc_info=True,
                )

        await asyncio.gather(*(_safe(cb) for cb in callbacks))

    def topics(self) -> List[str]:
        """Return the list of topics with at least one subscriber."""
        return list(self._subscribers.keys())


# Module-level singleton consumed by ``routers/websocket.py`` and any
# future in-process telemetry consumers. Phase 4 will publish to this
# bus from the WebSocket broadcast loop.
default_telemetry_bus = TelemetryBus()


__all__ = ["TelemetryBus", "default_telemetry_bus"]