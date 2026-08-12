"""HTTP router for the temperature module.

The router is mounted by the registry under
``/api/v1/modules/temperature``. It exposes:

* ``GET  /sensors``               — list all temperature sensors.
* ``POST /sensors/{name}/target`` — set a sensor's target temperature.

The router intentionally has no ``prefix`` argument — the registry
prefixes it when mounting.

The :func:`_collect_sensors` helper is the single source of truth
for reading the sensor dict; the HTTP endpoint delegates to it and
the base-thread snapshot (``routers/base_thread.py``) imports the
same helper so the two surfaces stay byte-for-byte identical.
"""

import logging
from typing import Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from hardware import execute_sync_cmd, get_machine_stat

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
    and reused by the legacy ``GET /sensors`` endpoint so the wire
    shape stays consistent.
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


class SensorsResponse(BaseModel):
    """Response body for ``GET /sensors``."""

    sensors: Dict[str, Dict[str, float]] = Field(
        default_factory=dict,
        description=(
            "Map of sensor name to its current state. Each entry has "
            "an 'actual' reading and, when controllable, a 'target'."
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


def _collect_sensors() -> Dict[str, Dict[str, float]]:
    """Read the live sensor dict from the stat channel.

    Returns a plain dict (sensor name -> ``{actual, target}``) so
    both the HTTP endpoint and the base-thread snapshot can
    serialise it the same way. Falls back to ``{}`` when the NML
    channel is offline — the dashboard's empty-state UI handles
    the no-data case cleanly.
    """
    stat = get_machine_stat()
    if stat is None:
        return {}
    poll = getattr(stat, "poll", None)
    if callable(poll):
        poll()
    sensors = getattr(stat, "temperatures", None) or {}
    return {name: dict(values) for name, values in sensors.items()}


@router.get(
    "/sensors",
    response_model=SensorsResponse,
    summary="List Temperature Sensors",
    description=(
        "Return the current sensor dictionary as exposed by the "
        "hardware layer. Polls the underlying stat object first so "
        "fresh readings are returned even if the WebSocket "
        "telemetry loop has not yet broadcast them."
    ),
)
def list_sensors() -> SensorsResponse:
    """List all temperature sensors known to the hardware layer."""
    return SensorsResponse(sensors=_collect_sensors())


@router.post(
    "/sensors/{name}/target",
    response_model=SetTargetResponse,
    summary="Set Sensor Target Temperature",
    description=(
        "Dispatch a ``set_temperature`` command to the hardware layer "
        "for the named sensor. The command is forwarded verbatim via "
        ":func:`hardware.execute_sync_cmd`; the simulation thread "
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
    if not name or not isinstance(name, str):
        raise HTTPException(
            status_code=400,
            detail="Sensor name must be a non-empty string",
        )
    if name != req.sensor_name:
        logger.debug(
            "sensor_name in body (%r) differs from URL (%r); URL wins",
            req.sensor_name,
            name,
        )
    try:
        result = execute_sync_cmd("set_temperature", 0, name, req.target)
    except HTTPException:
        # ``execute_sync_cmd`` already produces actionable HTTP errors.
        raise
    except Exception as exc:  # noqa: BLE001 - defensive: surface any failure
        logger.error("set_temperature(%s, %s) failed: %s", name, req.target, exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return SetTargetResponse(
        status=result.get("status", "success"),
        sensor_name=name,
        target=req.target,
    )


__all__ = [
    "router",
    "SetTargetRequest",
    "SetTargetResponse",
    "SensorsResponse",
    "SensorReading",
    "_collect_sensors",
]
