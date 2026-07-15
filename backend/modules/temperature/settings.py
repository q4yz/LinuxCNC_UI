"""Pydantic defaults model for the temperature module settings.

These fields are persisted via the registry's canonical settings
endpoints (``/api/v1/modules/temperature/settings``) and consumed by
the **frontend** store (see
``frontend/src/modules/temperature/store.js``). The backend does not
read them yet — Phase 5 may add server-side enforcement.

Field semantics:

* ``sample_period_ms`` — Backend-side polling cadence hint for the
  hardware layer (0.5 s by default). The mock's simulation loop
  already runs at 0.5 s; this is a forward-compatibility knob.
* ``ambient_celsius`` — Ambient temperature the simulator uses as a
  floor when sensors cool toward ``target``. 25 °C by default.
* ``history_window_seconds`` — How many seconds of temperature
  history the frontend chart retains. Drives the rolling-window
  prune cadence. Default 10 s.
* ``history_poll_interval_ms`` — How often the frontend snapshot
  loop pushes a point into history. Default 1000 ms.
"""

from pydantic import BaseModel, Field


class TemperatureSettings(BaseModel):
    """Pydantic defaults merged underneath user-persisted settings."""

    sample_period_ms: int = Field(
        default=500,
        ge=100,
        le=5000,
        description="Server-side polling cadence hint in milliseconds.",
    )
    ambient_celsius: float = Field(
        default=25.0,
        ge=-50.0,
        le=100.0,
        description="Ambient temperature floor for the simulator (°C).",
    )
    history_window_seconds: int = Field(
        default=10,
        ge=1,
        le=600,
        description="Seconds of history the frontend chart keeps.",
    )
    history_poll_interval_ms: int = Field(
        default=1000,
        ge=100,
        le=10000,
        description="Milliseconds between frontend history snapshots.",
    )


__all__ = ["TemperatureSettings"]
