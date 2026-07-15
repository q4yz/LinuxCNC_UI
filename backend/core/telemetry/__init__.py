"""Telemetry package: typed wrappers around the existing WebSocket transport.

This package is intentionally thin during Phase 2b/2c: it owns the
shell abstractions (:class:`core.telemetry.bus.TelemetryBus`) but does
**not** rewrite the existing WebSocket transport that lives in
``routers/websocket.py``. That refactor is Phase 4 work.

Phase 2c ships:

* :class:`TelemetryBus` — an opt-in *by-reference* pub/sub channel
  intended for high-frequency telemetry consumers (10-100 Hz) that
  cannot afford the Pydantic model re-instantiation overhead enforced
  by :class:`core.event_bus.EventBus`.
* :func:`default_telemetry_bus` — a module-level singleton that
  ``routers/websocket.py`` can publish to and that frontends can
  consume via the per-module ``TelemetryBus`` wrapper.
"""