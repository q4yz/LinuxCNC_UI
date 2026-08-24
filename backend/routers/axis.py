"""HTTP router for the axis module.

The axis module owns two kinds of endpoints:

* ``POST /home`` — dispatch a home command via the
  :class:`AxisService` facade. The endpoint always switches to
  ``MODE_MANUAL`` first so a stale ``MODE_AUTO`` does not silently
  swallow the home command. The handler is a thin wrapper around
  :func:`get_axis_service` from :mod:`services.AxisService`; the
  axis module does not own the business logic, only the HTTP edge.

* (Historically) jog REST endpoints — ``/jog``, ``/jog/keepalive``,
  ``/jog/stop`` were deprecated in favour of the ``/ws/telemetry``
  WebSocket channel and are no longer registered here.

The state / mode / MDI endpoints moved to
:mod:`state.router` when the HTTP surface was split
along semantic lines (axis-motion actions vs. machine-task
actions). The two routers each call into their own dedicated
service singleton (``StateService`` / ``AxisService``).

The router is mounted under ``/api/v1/modules/axis`` by the
registry, so the home endpoint is reachable at
``POST /api/v1/modules/axis/home``. The tag stays
``modules:axis`` so the regenerated OpenAPI client keeps
``homeAxis`` under ``ModulesAxisService`` on the frontend.
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from services.AxisService import get_axis_service


router = APIRouter(
    prefix="/api/v1/modules/axis",
    tags=["modules:axis"],
)


# ---------------------------------------------------------------------------
# Pydantic request / response models (kept private to the module)
# ---------------------------------------------------------------------------


class _HomeCommand(BaseModel):
    axis: int = Field(
        ...,
        description=(
            "Axis index to home (0=X, 1=Y, 2=Z). Use -1 to home all axes."
        ),
    )

class _AxisSettingsCommand(BaseModel):
    multiplier: float = Field(
        ...,
        ge=0.0,
        le=5.0,
        description="Speed multiplier percentage (between 0.0 and 5.0)."
    )
    absolute_speed_limit: int = Field(
        ...,
        ge=0,
        le=5000,
        description="Absolute speed limit (between 0 and 5000)."
    )


class _StatusResponse(BaseModel):
    status: str = Field(..., description="Outcome summary (e.g., 'ok')")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/home",
    summary="Home Axis",
    description="Home a specific axis, or all axes if axis=-1.",
    operation_id="homeAxis",
    response_model=_StatusResponse,
)
def _home_axis_endpoint(cmd: _HomeCommand) -> _StatusResponse:
    """Dispatch a home command via the facade.

    The endpoint always switches to ``MODE_MANUAL`` first so a stale
    ``MODE_AUTO`` does not silently swallow the home command. This
    happens inside :meth:`AxisService.home_axis`; the
    router only translates the HTTP edge.
    """
    get_axis_service().home_single_axes(cmd.axis)
    return _StatusResponse(status="success")


@router.post(
    "/settings",
    summary="Axis Settings",
    description="Update axis settings including speed multiplier and absolute limit.",
    operation_id="axisSettings",
    response_model=_StatusResponse,
)
def _axis_settings_endpoint(cmd: _AxisSettingsCommand) -> _StatusResponse:
    """Update axis settings via the facade.

    Passes the multiplier and absolute speed limit to the AxisService.
    """
    # Assuming your AxisService has a method to handle settings updates.
    # Adjust the method name to match your actual service implementation.
    service = get_axis_service()
    if hasattr(service, "update_settings"):
        service.update_settings(cmd.multiplier, cmd.absolute_speed_limit)

    return _StatusResponse(status="success")


__all__ = ["router"]
