"""HTTP router for the temperature module.

The router is mounted by the registry under
``/api/v1/modules/temperature``. It exposes:

* ``POST /sensors/{name}/target`` — set a sensor's target temperature.

The router intentionally has no ``prefix`` argument — the registry
prefixes it when mounting.

The :func:`collect_sensors` helper is the single source of truth
for reading the sensor dict; it lives in
:mod:`modules.temperature.service` and the base-thread snapshot
(``routers/base_thread.py``) consumes the same helper so the
canonical 1 Hz snapshot is the only public surface for sensor
data. The legacy ``GET /sensors`` endpoint was superseded by the
snapshot and has been removed.

The router delegates every hardware-touching call to
:func:`get_temperature_service` in :mod:`modules.temperature.service`
— the router itself does not import ``hardware.*`` so the rule "no
router is allowed to import any hardware file" stays enforced.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel, Field

from modules.temperature.service import get_temperature_service

logger = logging.getLogger("backend.modules.temperature.router")

router = APIRouter()


class SetTargetRequest(BaseModel):
    """Request body for ``POST /sensors/{name}/target``."""

    sensor_name: str = Field(
        ...,
        min_length=1,
        description="Logical sensor identifier (e.g., 'extruder', 'bed').",
    )

    target: float = Field(
        ...,
        ge=0.0,
        le=400.0,
        description="Target temperature in Celsius (0–400 °C).",
    )


class SensorReading(BaseModel):
    """One temperature sensor reading.

    Used by the snapshot response model (``routers/base_thread.py``)
    so the wire shape stays consistent across the slow-channel surface.
    """

    actual: float = Field(
        ...,
        description="Current temperature reading in Celsius.",
    )
    target: float = Field(
        ...,
        description=(
            "Set-point temperature in Celsius. ``0`` for sensors "
            "without a controllable heater."
        ),
    )


class SetTargetResponse(BaseModel):
    """Response body for ``POST /sensors/{name}/target``."""

    status: str = Field(
        default="success",
        description="Outcome reported by the hardware layer.",
    )

    sensor_name: str = Field(
        ...,
        description="Echo of the sensor name that was updated.",
    )

    target: float = Field(
        ...,
        description="Echo of the target value that was applied.",
    )


@router.post(
    "/sensors/{name}/target",
    response_model=SetTargetResponse,
    summary="Set Sensor Target Temperature",
    description=(
        "Dispatch a ``set_temperature`` command to the hardware layer "
        "for the named sensor. The router delegates to "
        ":class:`TemperatureService.set_target`; the simulation thread "
        "(when enabled) starts on first invocation and runs "
        "process-wide."
    ),
)
def set_target(name: str, req: SetTargetRequest) -> SetTargetResponse:
    """Set the target temperature for ``name``.

    The ``sensor_name`` field in the body is accepted but ``name``
    from the URL takes precedence — the URL is the canonical
    identifier and the body field is kept for backward compatibility
    with the legacy ``POST /api/v1/machine/temperature`` payload.
    """
    if name != req.sensor_name:
        logger.debug(
            "sensor_name in body (%r) differs from URL (%r); URL wins",
            req.sensor_name,
            name,
        )

    result = get_temperature_service().set_target(name, req.target)
    return SetTargetResponse(
        status=result.get("status", "success"),
        sensor_name=name,
        target=req.target,
    )


__all__ = [
    "router",
    "SetTargetRequest",
    "SetTargetResponse",
    "SensorReading",
]