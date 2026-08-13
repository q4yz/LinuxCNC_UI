"""HTTP router for the machine-state module.

Exposes the four endpoints that operate on the machine's overall
state rather than on a specific axis::

    GET  /state   — read the clean ``MachineState`` snapshot.
    POST /state   — set machine E-Stop / Power state.
    POST /mode    — change the task mode (manual / auto / mdi).
    POST /mdi     — dispatch a single MDI (G-Code) command.

The ``/home`` endpoint lives in :mod:`backend.modules.axis.router`
because homing is an axis-motion action; this module owns everything
else that used to live on the historical
``backend.services.machine_service::machine_control_router``.

Each handler is a thin wrapper around :class:`StateService`
in :mod:`backend.modules.state.service`. The router imports only
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
from typing import List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from modules.state.service import get_state_service
from services.console_logger import LogLevel, get_console_logger


logger = logging.getLogger("backend.modules.state.router")


router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic request / response models (kept private to the module)
# ---------------------------------------------------------------------------


class _StateCommand(BaseModel):
    state: str = Field(
        ...,
        description=(
            "Target machine state: 'on', 'off', 'estop', or 'estop_reset'"
        ),
    )


class _ModeCommand(BaseModel):
    mode: str = Field(
        ...,
        description="Target task mode: 'manual', 'auto', or 'mdi'",
    )


class _MdiCommand(BaseModel):
    command: str = Field(..., description="G-code / MDI command string to execute")


class _StateSnapshot(BaseModel):
    """Clean + diagnostic machine-state snapshot for ``GET /state``.

    ``state`` is the operator-facing :class:`MachineState` enum
    value (lowercase string). ``raw_*`` fields are diagnostic
    only — they are intentionally prefixed so a future refactor
    can drop them without breaking the wire format.
    """

    state: str = Field(
        ...,
        description=(
            "Clean MachineState enum value (e.g. 'idle', 'running')."
        ),
    )
    raw_task_state: int = Field(
        ...,
        description="linuxcnc NML task_state (diagnostic only).",
    )
    raw_estop: int = Field(
        ...,
        description="linuxcnc NML estop bit (diagnostic only).",
    )
    raw_interp_state: int = Field(
        ...,
        description="linuxcnc NML interp_state (diagnostic only).",
    )
    file: str = Field(
        default="",
        description="Loaded G-code file path; empty when none.",
    )
    homed: List[int] = Field(
        ...,
        description="Per-axis homed flags (one entry per axis).",
    )


class _StatusResponse(BaseModel):
    status: str = Field(..., description="Outcome summary (e.g., 'ok')")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/state",
    tags=["modules:machine_state"],
    summary="Read Machine State",
    description=(
        "Return the clean MachineState snapshot. The ``state`` "
        "field is the operator-facing enum; ``raw_*`` fields are "
        "diagnostic only and may be dropped in a future release."
    ),
    operation_id="getMachineState",
    response_model=_StateSnapshot,
)
def _get_state_endpoint() -> _StateSnapshot:
    """Read-side facade — delegates to
    :meth:`StateService.get_state_snapshot` and lets
    FastAPI's response-model coercion turn the dict into the
    documented :class:`_StateSnapshot` shape.
    """
    snapshot = get_state_service().get_state_snapshot()
    return _StateSnapshot(**snapshot)


@router.post(
    "/state",
    tags=["modules:machine_state"],
    summary="Set Machine State",
    description="Toggle machine E-Stop or Power state.",
    operation_id="setMachineState",
    response_model=_StatusResponse,
)
def _set_state_endpoint(cmd: _StateCommand) -> _StatusResponse:
    """Translate ``state`` via the facade and dispatch.

    ``ValueError`` from the service (unknown state name) is
    translated to ``400 Invalid state`` so the FastAPI contract
    matches the historical router's surface.
    """
    try:
        get_state_service().set_state(cmd.state)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid state")
    return _StatusResponse(status="success")


@router.post(
    "/mode",
    tags=["modules:machine_state"],
    summary="Set Machine Mode",
    description="Change the machine task mode (manual, auto, mdi).",
    operation_id="setMachineMode",
    response_model=_StatusResponse,
)
def _set_mode_endpoint(cmd: _ModeCommand) -> _StatusResponse:
    """Translate ``mode`` via the facade and dispatch."""
    try:
        get_state_service().set_mode(cmd.mode)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid mode")
    return _StatusResponse(status="success")


@router.post(
    "/mdi",
    tags=["modules:machine_state"],
    summary="Run MDI Command",
    description=(
        "Execute a single MDI (G-Code) command. Automatically "
        "switches the machine to MDI mode before dispatching the "
        "command to the hardware layer."
    ),
    operation_id="runMdiCommand",
    response_model=_StatusResponse,
)
def _run_mdi_endpoint(cmd: _MdiCommand) -> _StatusResponse:
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
    return _StatusResponse(status="success")


__all__ = ["router"]