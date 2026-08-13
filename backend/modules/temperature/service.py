"""Temperature module service — :class:`TemperatureService` + :func:`read_temperature`.

This is the canonical home for the temperature-sensor telemetry
collector that used to live as a module-level helper in
``backend.services.machine_service``, plus the
``set_temperature`` dispatch that used to live in the temperature
router. The base-thread snapshot router (``routers/base_thread.py``)
imports :func:`get_temperature_service` (or ``collect_sensors``
directly) from this module; the temperature router imports
:func:`set_target`; the tools module's tool-telemetry overlay
imports :func:`read_temperature` to decorate heating tools with
their runtime ``actual`` / ``target`` readings.
"""
from __future__ import annotations

import logging
from typing import Dict, Optional

from fastapi import HTTPException
from hardware import connection
from hardware import linuxcnc_mock
from hardware.connection import execute_sync_cmd

logger = logging.getLogger("backend.modules.temperature.service")


def read_temperature(sensor_id: str) -> Optional[Dict[str, float]]:
    """Return the live temperature reading for ``sensor_id``.

    Reads the mock's ``_machine_state.temperatures`` dict under its
    lock so concurrent operators reading the snapshot never see a
    torn dict. Returns ``None`` when the sensor has not been seeded
    yet (e.g. a test boot without a ``hardware.json`` that names it).

    The :mod:`modules.tools.service` overlay uses this helper to
    decorate heating tools (``extruder`` / ``heated_bed``) with their
    runtime readings.
    """
    if not isinstance(sensor_id, str) or not sensor_id:
        return None
    with linuxcnc_mock._machine_state.lock:  # noqa: SLF001
        reading = linuxcnc_mock._machine_state.temperatures.get(sensor_id)
    if not reading:
        return None
    return {
        "actual": reading.get("actual", 0.0),
        "target": reading.get("target", 0.0),
    }


class TemperatureService:
    """Temperature-sensor telemetry + dispatch facade.

    Two responsibilities live here:

    * **Telemetry:** :meth:`collect_sensors` reads the live
      ``stat.temperatures`` dict from the NML channel and returns a
      plain ``{sensor_name: {actual, target}}`` dict so the
      base-thread snapshot can serialise it the same way. Falls
      back to ``{}`` when the NML channel is offline.
    * **Dispatch:** :meth:`set_target` translates the operator-facing
      ``POST /sensors/{name}/target`` payload into a
      ``set_temperature`` command and forwards it to the hardware
      layer. Returns the ``set_temperature`` result dict so the
      router can echo ``status`` back to the caller.
    """

    def collect_sensors(self) -> Dict[str, Dict[str, float]]:
        """Read the live sensor dict from the stat channel."""
        stat = connection.get_machine_stat()
        if stat is None:
            return {}
        poll = getattr(stat, "poll", None)
        if callable(poll):
            poll()
        sensors = getattr(stat, "temperatures", None) or {}
        return {name: dict(values) for name, values in sensors.items()}

    def set_target(self, name: str, target: float) -> dict:
        """Dispatch ``set_temperature`` for the named sensor.

        Raises :class:`HTTPException` (400 / 500) for the same
        reasons the historical router did — caller-side error
        translation is intentionally kept in the service so the
        router stays thin.
        """
        if not name or not isinstance(name, str):
            raise HTTPException(
                status_code=400,
                detail="Sensor name must be a non-empty string",
            )

        try:
            result = execute_sync_cmd("set_temperature", 0, name, target)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001 - defensive
            logger.error(
                "set_temperature(%s, %s) failed: %s", name, target, exc
            )
            raise HTTPException(status_code=500, detail=str(exc))

        return result


_temperature_service: Optional[TemperatureService] = None


def get_temperature_service() -> TemperatureService:
    """Lazy module-level singleton (sensor telemetry / dispatch facade)."""
    global _temperature_service
    if _temperature_service is None:
        _temperature_service = TemperatureService()
    return _temperature_service


def collect_sensors() -> Dict[str, Dict[str, float]]:
    """Module-level convenience wrapper for backward compatibility."""
    return get_temperature_service().collect_sensors()


__all__ = [
    "TemperatureService",
    "get_temperature_service",
    "collect_sensors",
    "read_temperature",
]