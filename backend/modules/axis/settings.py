"""Pydantic defaults model for the machine module settings.

The schema documents the canonical shape the
:class:`core.settings_store.SettingsStore` will serve on
``GET /api/v1/modules/machine/settings``. New keys can be added in later
releases without breaking existing deployments — the store merges the
defaults underneath the persisted payload so a missing key is filled in
from this schema's defaults on every read.

Field semantics:

* ``jog_watchdog_timeout_ms`` — Backend-side keep-alive watchdog
  window. The jog safety watchdog reads this value once when it
  starts in :meth:`AxisModule.on_load`; the value is settable at
  runtime via PUT ``/settings``, but the watchdog only re-reads it
  on a restart (which is acceptable for v1). Changing this on the fly
  is unsafe — operators should set it and reboot.
* ``default_jog_velocity`` — Initial velocity for a fresh continuous
  jog before the slider is touched. The machine module's frontend
  store reads this setting at startup and before a first jog.
* ``keepalive_interval_ms`` — Frontend-side keep-alive cadence hint.
  The machine module store uses this value instead of a hard-coded
  250 ms interval, while retaining that value as the safe fallback.
* ``estop_disables_power`` — Persisted policy flag exposed with the
  module settings schema. The hardware's native E-STOP transition
  remains authoritative; a future settings UI can use this flag when
  composing higher-level power workflows.

These defaults match the historical hard-coded values that used to live
in ``routers/jog.py`` (500 ms timeout, 250 ms keepalive, velocity 500)
and ``routers/machine.py``. Migrating them out of the source into this
schema is what makes the module user-configurable without touching the
router code.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class MachineSettings(BaseModel):
    """User-tunable knobs for the machine module.

    Attributes:
        jog_watchdog_timeout_ms: Continuous-jog watchdog window in
            milliseconds. Must be between 100 ms and 5000 ms.
        default_jog_velocity: Velocity (mm/min) used by a fresh jog
            when no user setting overrides it.
        keepalive_interval_ms: Frontend-side keep-alive cadence hint
            in milliseconds. The hard floor is 50 ms; the soft ceiling
            of 2000 ms prevents the watchdog from timing out a slow
            keep-alive.
        estop_disables_power: Persisted policy flag for higher-level
            E-STOP/power workflows. The native hardware transition is
            authoritative in this version.
    """

    jog_watchdog_timeout_ms: int = Field(
        default=500,
        ge=100,
        le=5000,
        description=(
            "Continuous-jog watchdog window in milliseconds. The "
            "safety watchdog reads this on startup."
        ),
    )
    default_jog_velocity: float = Field(
        default=500.0,
        ge=1.0,
        description=(
            "Default velocity in mm/min used by a fresh continuous "
            "jog when the operator has not chosen another value."
        ),
    )
    keepalive_interval_ms: int = Field(
        default=250,
        ge=50,
        le=2000,
        description=(
            "Frontend-side keep-alive cadence hint in milliseconds. "
            "Must be lower than ``jog_watchdog_timeout_ms``."
        ),
    )
    estop_disables_power: bool = Field(
        default=True,
        description=(
            "Persisted policy flag for higher-level E-STOP and power "
            "workflows; native hardware state transitions remain "
            "authoritative."
        ),
    )


__all__ = ["MachineSettings"]
