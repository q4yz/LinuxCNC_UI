"""HTTP router for the machine-state module.

Exposes the four endpoints that operate on the machine's overall
state rather than on a specific axis::

    GET  /state   — read the clean ``MachineState`` snapshot.
    POST /state   — set machine E-Stop / Power state.
    POST /mode    — change the task mode (manual / auto / mdi).
    POST /mdi     — dispatch a single MDI (G-Code) command.

The ``/home`` endpoint lives in :mod:`axis.router`
because homing is an axis-motion action; this module owns everything
else that used to live on the historical
``backend.services.machine_service::machine_control_router``.

Each handler is a thin wrapper around :class:`StateService`
in :mod:`backend.services.StateService`. The router imports only
the singleton accessor (``get_state_service``) — never the
facade class — so the layer-2 split can evolve independently of the
HTTP surface.

Tag is ``modules:machine_state`` so the regenerated OpenAPI client
groups these operations under ``ModulesMachineStateService``. The
``/home`` operation keeps the ``modules:axis`` tag and therefore
stays inside ``ModulesAxisService`` on the frontend side.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from services.StateService import get_state_service
from services.ConsoleLogger import LogLevel, get_console_logger
from models.state.state_models import (
    MdiCommand,
    ModeCommand,
    StateCommand,
    StateSnapshotResponse,
    StatusResponse,
)


logger = logging.getLogger("backend.state_service")


router = APIRouter(
    prefix="/api/v1/modules/machine_state",
    tags=["modules:machine_state"],
)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/state",    summary="Read Machine State",
    description=(
        "Return the clean MachineState snapshot. The ``state`` "
        "field is the operator-facing enum; ``raw_*`` fields are "
        "diagnostic only and may be dropped in a future release."
    ),
    operation_id="getMachineState",
    response_model=StateSnapshotResponse,
)
def _get_state_endpoint() -> StateSnapshotResponse:
    """Read-side facade — delegates to
    :meth:`StateService.get_state_snapshot`, which already returns
    the documented :class:`StateSnapshotResponse` shape.
    """
    return get_state_service().get_state_snapshot()


@router.post(
    "/state",    summary="Set Machine State",
    description="Toggle machine E-Stop or Power state.",
    operation_id="setMachineState",
    response_model=StatusResponse,
)
def _set_state_endpoint(cmd: StateCommand) -> StatusResponse:
    """Translate ``state`` via the facade and dispatch.

    ``ValueError`` from the service (unknown state name) is
    translated to ``400 Invalid state`` so the FastAPI contract
    matches the historical router's surface.
    """
    try:
        get_state_service().set_state(cmd.state)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid state")
    return StatusResponse(status="success")


@router.post(
    "/mode",    summary="Set Machine Mode",
    description="Change the machine task mode (manual, auto, mdi).",
    operation_id="setMachineMode",
    response_model=StatusResponse,
)
def _set_mode_endpoint(cmd: ModeCommand) -> StatusResponse:
    """Translate ``mode`` via the facade and dispatch."""
    try:
        get_state_service().set_mode(cmd.mode)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid mode")
    return StatusResponse(status="success")


@router.post(
    "/mdi",    summary="Run MDI Command",
    description=(
        "Execute a single MDI (G-Code) command. Automatically "
        "switches the machine to MDI mode before dispatching the "
        "command to the hardware layer."
    ),
    operation_id="runMdiCommand",
    response_model=StatusResponse,
)
def _run_mdi_endpoint(cmd: MdiCommand) -> StatusResponse:
    """Dispatch a single MDI command via the facade.

    The handler mirrors the command + response to the persistent
    console history so the on-disk log shows every command the
    operator issued, even if the in-browser console clears its
    buffer. This was the historical behaviour of the merged
    machine router; the console logger is the canonical source
    of truth for offline replay and is owned by
    :mod:`backend.services.console_logger`.
    """
    logger.info("Running MDI: %s", cmd.command)
    console_logger = get_console_logger()
    console_logger.log_command(cmd.command)
    try:
        get_state_service().run_mdi(cmd.command)
    except HTTPException as exc:
        console_logger.log_response(
            f"Error: {exc.detail}",
            level=LogLevel.ERROR,
        )
        raise
    console_logger.log_response(
        f"Executed: {cmd.command}",
        level=LogLevel.INFO,
    )
    return StatusResponse(status="success")


@router.post(
    "/estop/activate",
    summary="Engage E-Stop",
    description=(
        "Critical e-stop activation. Writes directly to "
        "``halui.estop.activate`` so the servo thread reacts within "
        "one period (~1 ms) instead of the multi-stage NML round-trip "
        "that ``POST /state`` takes. Always-engage: idempotent on "
        "repeat presses; pressing the button while ESTOP is already "
        "active is a no-op semantically."
    ),
    operation_id="activateEstop",
    response_model=StatusResponse,
)
def _activate_estop_endpoint() -> StatusResponse:
    """Drive ``halui.estop.activate`` directly.

    Used only by the global E-Stop header button (``EStopHeader.vue``).
    The state bar's smaller E-STOP button still goes through
    ``POST /state`` via :func:`_set_state_endpoint` so the two
    affordances keep distinct behaviour contracts.
    """
    try:
        get_state_service().activate_estop()
    except HTTPException:
        # ``activate_estop`` raises 503 on HAL write failure; let it
        # propagate so the operator sees the wiring fault instead of
        # a misleading 200 OK.
        raise
    return StatusResponse(status="success")


__all__ = ["router"]