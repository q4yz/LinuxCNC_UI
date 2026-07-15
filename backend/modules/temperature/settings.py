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
* ``unit`` — Display unit used by the chart and control box.
  ``"celsius"`` (default) or ``"kelvin"``. The backend never
  converts; conversion is purely display-side in the frontend
  store.
* ``sensor_colors`` — Per-sensor CSS colour map (``sensor name``
  → ``"#RRGGBB"``). The frontend uses this for both the control
  box swatches and the chart series so the identity is stable
  across panels. New sensors added by the backend fall back to a
  deterministic default colour (``#A855F7`` — purple) in the
  frontend; the map can be extended via
  ``PUT /api/v1/modules/temperature/settings``.

The previously-defined ``history_window_seconds`` and
``history_poll_interval_ms`` fields have been removed. They were
never honoured in practice — the frontend chart is now locked to
a fixed 30-second window with 1-second ticks. Surfacing them as
configurable only invited operators to dial in values the chart
did not actually use.
"""

from typing import Dict, Literal

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
    unit: Literal["celsius", "kelvin"] = Field(
        default="celsius",
        description=(
            "Display unit for the chart and control box. "
            "'celsius' (default) or 'kelvin'. Conversion (K = °C + "
            "273.15) happens in the frontend."
        ),
    )
    sensor_colors: Dict[str, str] = Field(
        default_factory=lambda: {
            "extruder": "#EF4444",
            "bed": "#3B82F6",
            "cpu": "#10B981",
        },
        description=(
            "Per-sensor CSS colour map (sensor name → '#RRGGBB'). "
            "Used by both the control-box swatches and the chart "
            "series so the visual identity stays in sync. Unknown "
            "sensors fall back to #A855F7 (purple) in the frontend."
        ),
    )


__all__ = ["TemperatureSettings"]
