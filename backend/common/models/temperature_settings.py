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
  across panels. The defaults are seeded from the active heater
  list (see :func:`seed_colors`); new sensors introduced at
  runtime fall back to ``#A855F7`` (purple) in the frontend, and
  the operator's persisted overrides always win the
  ``SettingsStore`` merge.

The previously-defined ``history_window_seconds`` and
``history_poll_interval_ms`` fields have been removed. They were
never honoured in practice — the frontend chart is now locked to
a fixed 30-second window with 1-second ticks. Surfacing them as
configurable only invited operators to dial in values the chart
did not actually use.

The ``cpu`` / ``extruder`` / ``bed`` triple that used to live in
the hard-coded default factory has been removed — see issue #97.
Operators who want a CPU gauge add a ``cpu`` heater to
``machine.cfg``; the seeded colours are deterministic (sorted
input, 6-colour palette, modulo wrap).
"""

from typing import Dict, List, Literal

from pydantic import BaseModel, Field


#: Six-entry palette indexed by sorted-name order. Picked so any two
#: adjacent hues are easily distinguishable on the chart and the
#: control-box swatches. ``#A855F7`` is intentionally **not** in this
#: palette — it stays as the frontend's "unknown sensor" fallback
#: colour.
DEFAULT_COLOR_PALETTE: tuple[str, ...] = (
    "#EF4444",  # red
    "#3B82F6",  # blue
    "#10B981",  # green
    "#F59E0B",  # amber
    "#8B5CF6",  # violet
    "#EC4899",  # pink
)


def seed_colors(heater_names: List[str] | None) -> Dict[str, str]:
    """Assign a deterministic colour to each heater name.

    The input is sorted alphabetically so the same heater list always
    gets the same colour regardless of the order ``hardware.json``
    happened to write it in. The 6-colour palette wraps with modulo
    so a 7-sensor machine still gets a unique colour for every entry
    (the palette is small, but modulo wrap is the documented contract
    — no operator complaint has surfaced about the wrap).

    An empty or ``None`` input yields an empty dict so a machine with
    no heaters (or one whose ``hardware.json`` has not yet been
    deployed) does not leak the legacy three-sensor palette.
    """
    if not heater_names:
        return {}
    palette = DEFAULT_COLOR_PALETTE
    return {
        name: palette[i % len(palette)]
        for i, name in enumerate(sorted(heater_names))
    }


class TemperatureSettings(BaseModel):
    """Pydantic defaults merged underneath user-persisted settings.

    The module's :meth:`get_settings_model` factory passes the
    active heater list to :func:`seed_colors` so the seeded
    ``sensor_colors`` always match the machine the operator
    deployed. New keys added to a future release inherit the same
    forward-compatibility semantics — see ``SettingsStore`` docs.
    """

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
        default_factory=lambda: {},
        description=(
            "Per-sensor CSS colour map (sensor name → '#RRGGBB'). "
            "Used by both the control-box swatches and the chart "
            "series so the visual identity stays in sync. The "
            "frontend seeds each sensor with the colour assigned "
            "by :func:`seed_colors`; unknown sensors fall back to "
            "#A855F7 (purple)."
        ),
    )


__all__ = ["TemperatureSettings", "seed_colors", "DEFAULT_COLOR_PALETTE"]