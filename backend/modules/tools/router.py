"""HTTP router for the tools module.

The router is mounted by the registry under
``/api/v1/modules/tools``. It exposes two endpoints that drive the
machine via MDI commands:

* ``POST /spindle`` — start / reverse / stop a spindle using the
  canonical ``M3 S{speed}`` / ``M4 S{speed}`` / ``M5`` codes.
* ``POST /extruder`` — extrude or retract material on a 3D-printer
  extruder axis using relative (``G91``) ``G1 E{dist} F{speed}``
  moves, restoring absolute (``G90``) mode afterwards.

Both endpoints share the same safety preamble: switch the task into
``MODE_MDI`` first (blocking until the mode change is acknowledged)
so the subsequent ``mdi`` call is accepted by the interpreter. The
MDI dispatch itself is non-blocking (``wait_complete(timeout=0)``)
because the operator's tool panel is fire-and-forget — multiple
consecutive presses should queue cleanly rather than stall on a
hard wait.

The router intentionally has no ``prefix`` argument — the registry
prefixes it when mounting.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from hardware import execute_sync_cmd, linuxcnc

logger = logging.getLogger("backend.modules.tools.router")


# ---------------------------------------------------------------------- #
# Constants                                                               #
# ---------------------------------------------------------------------- #


# Canonical LinuxCNC MDI strings. Kept module-private so the router
# functions below stay readable. The constants are exported through
# :data:`__all__` for unit tests that want to assert the exact
# strings the endpoint emits (Issue #64 acceptance criteria).
M3_FORWARD = "M3 S{speed}"
M4_BACKWARD = "M4 S{speed}"
M5_STOP = "M5"
G91_RELATIVE = "G91"
G90_ABSOLUTE = "G90"
G1_EXTRUDE = "G1 E{dist} F{speed}"

# Allowed action vocabulary. Centralised so the request validators
# below share a single source of truth.
_SPINDLE_ACTIONS = {"forward", "backward", "stop"}
_EXTRUDER_ACTIONS = {"extrude", "retract"}


# ---------------------------------------------------------------------- #
# Pydantic request models                                                 #
# ---------------------------------------------------------------------- #


class SpindleCommand(BaseModel):
    """Request body for ``POST /spindle``.

    The ``tool_id`` is accepted verbatim and logged so operators can
    correlate a command with the spindle it targeted; the backend
    currently has only one physical spindle so the field is not
    interpreted by the hardware layer.
    """

    tool_id: str = Field(
        ...,
        min_length=1,
        description="Logical tool identifier (e.g., 'spindle_main').",
    )
    action: str = Field(
        ...,
        description="Spindle action: 'forward', 'backward', or 'stop'.",
    )
    speed: int = Field(
        ...,
        ge=0,
        le=200_000,
        description="Target RPM for 'forward' / 'backward'; ignored for 'stop'.",
    )


class ExtruderCommand(BaseModel):
    """Request body for ``POST /extruder``."""

    tool_id: str = Field(
        ...,
        min_length=1,
        description="Logical tool identifier (e.g., 'extruder_1').",
    )
    action: str = Field(
        ...,
        description="Extruder action: 'extrude' or 'retract'.",
    )
    distance: float = Field(
        ...,
        gt=0.0,
        le=1000.0,
        description="Absolute extrusion distance in mm (sign is applied by action).",
    )
    speed: int = Field(
        ...,
        gt=0,
        le=10_000,
        description="Feed rate in mm/min for the G1 move.",
    )


class ToolCommandResponse(BaseModel):
    """Generic response shape for both endpoints."""

    status: str = Field(
        default="success",
        description="Outcome reported by the hardware layer.",
    )
    command: str = Field(
        ...,
        description="The MDI string that was dispatched (or the M5 stop marker).",
    )
    tool_id: str = Field(
        ...,
        description="Echo of the tool id from the request body.",
    )


# ---------------------------------------------------------------------- #
# Endpoints                                                               #
# ---------------------------------------------------------------------- #


# No ``prefix`` — the registry mounts this router under
# ``/api/v1/modules/tools`` and tags it ``modules:tools``.
router = APIRouter(tags=["modules:tools"])


def _ensure_mdi_mode() -> None:
    """Switch the task into MDI mode and wait for the change to commit.

    The interpreter silently ignores ``mdi`` calls issued while the
    task is in ``MANUAL`` / ``AUTO`` mode (see
    :mod:`hardware.linuxcnc_mock`). The machine module's router
    uses the same ``mode`` + ``wait_complete(timeout=5)`` preamble
    before every ``mdi`` dispatch, so we mirror that here.
    """
    execute_sync_cmd(
        "mode",
        5,
        getattr(linuxcnc, "MODE_MDI", 3),
    )


def _dispatch_mdi(command: str) -> None:
    """Issue a single MDI command without waiting for completion.

    The operator's tool panel is fire-and-forget — multiple rapid
    presses should queue rather than block on a hard wait. We pass
    ``timeout=0`` to :func:`hardware.execute_sync_cmd` so the
    underlying ``mdi`` call returns immediately.
    """
    logger.info("tools mdi -> %s", command)
    execute_sync_cmd("mdi", 0, command)


@router.post(
    "/spindle",
    response_model=ToolCommandResponse,
    summary="Control Spindle",
    description=(
        "Start, reverse, or stop the spindle via the canonical "
        "LinuxCNC M-codes: ``M3 S{speed}`` (forward), "
        "``M4 S{speed}`` (backward), or ``M5`` (stop). The router "
        "switches the task into MDI mode before dispatching so the "
        "interpreter accepts the command."
    ),
    operation_id="controlSpindle",
)
def control_spindle(cmd: SpindleCommand) -> ToolCommandResponse:
    """Handle a spindle command request."""
    if cmd.action not in _SPINDLE_ACTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid spindle action: {cmd.action!r}",
        )

    _ensure_mdi_mode()

    if cmd.action == "forward":
        mdi = M3_FORWARD.format(speed=cmd.speed)
    elif cmd.action == "backward":
        mdi = M4_BACKWARD.format(speed=cmd.speed)
    else:  # cmd.action == "stop"
        # M5 ignores the S-word; the request body's ``speed`` is
        # accepted but unused so the front-end doesn't have to
        # branch on action before posting.
        mdi = M5_STOP

    _dispatch_mdi(mdi)
    return ToolCommandResponse(status="success", command=mdi, tool_id=cmd.tool_id)


@router.post(
    "/extruder",
    response_model=ToolCommandResponse,
    description=(
        "Extrude or retract material on the extruder axis. The "
        "router switches into relative distance mode (``G91``), "
        "issues a single ``G1 E{dist} F{speed}`` move — the sign "
        "of ``dist`` is inverted for the retract direction — and "
        "restores absolute mode (``G90``) so subsequent commands "
        "behave as expected."
    ),
    summary="Control Extruder",
    operation_id="controlExtruder",
)
def control_extruder(cmd: ExtruderCommand) -> ToolCommandResponse:
    """Handle an extruder command request."""
    if cmd.action not in _EXTRUDER_ACTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid extruder action: {cmd.action!r}",
        )

    _ensure_mdi_mode()

    # Per Issue #64: retract is a negative distance relative to the
    # extruder's positive-feed direction. The frontend passes an
    # always-positive ``distance`` so the operator never has to
    # remember the sign convention.
    signed_dist = cmd.distance if cmd.action == "extrude" else -cmd.distance

    _dispatch_mdi(G91_RELATIVE)
    move = G1_EXTRUDE.format(dist=signed_dist, speed=cmd.speed)
    _dispatch_mdi(move)
    _dispatch_mdi(G90_ABSOLUTE)

    return ToolCommandResponse(status="success", command=move, tool_id=cmd.tool_id)


__all__ = [
    "router",
    "SpindleCommand",
    "ExtruderCommand",
    "ToolCommandResponse",
    "M3_FORWARD",
    "M4_BACKWARD",
    "M5_STOP",
    "G91_RELATIVE",
    "G90_ABSOLUTE",
    "G1_EXTRUDE",
]