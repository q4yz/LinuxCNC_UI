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

from models.AxisModels import (
    AxisSettingsCommand,
    HomeAxisCommand,
    AxisStatusResponse,
)

from services.AxisService import get_axis_service


router = APIRouter(
    prefix="/api/v1/modules/axis",
    tags=["modules:axis"],
)


@router.post(
    "/home",
    summary="Home Axis",
    description="Home a specific axis by letter ('x' / 'y' / 'z'), or every axis when axis='all'.",
    operation_id="homeAxis",
    response_model=AxisStatusResponse,
)
def _home_axis_endpoint(cmd: HomeAxisCommand) -> AxisStatusResponse:
    """Dispatch a home command via the facade.

    The endpoint always switches to ``MODE_MANUAL`` first so a stale
    ``MODE_AUTO`` does not silently swallow the home command. This
    happens inside :meth:`AxisService.home_single_axes`; the
    router only translates the HTTP edge.
    """
    get_axis_service().home_single_axes(cmd.axis)
    return AxisStatusResponse(status="success")


@router.post(
    "/settings",
    summary="Axis Settings",
    description="Update axis settings including speed multiplier and absolute limit.",
    operation_id="axisSettings",
    response_model=AxisStatusResponse,
)
def _axis_settings_endpoint(cmd: AxisSettingsCommand) -> AxisStatusResponse:
    """Apply axis speed settings to the running LinuxCNC session."""
    get_axis_service().update_settings(cmd.multiplier, cmd.absolute_speed_limit)
    return AxisStatusResponse(status="success")


__all__ = ["router"]
