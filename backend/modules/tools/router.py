"""HTTP router for the tools module.

The router is mounted by the registry under
``/api/v1/modules/tools``. It exposes the three endpoints that
still drive the machine and operator commands:

* ``POST /tools/{id}/target`` — set the target temperature for a
  heating tool (extruder / heated_bed). The router looks up the
  tool's ``sensor`` reference and dispatches a ``set_temperature``
  to the hardware layer.
* ``POST /spindle`` — start / reverse / stop a spindle using the
  canonical ``M3 S{speed}`` / ``M4 S{speed}`` / ``M5`` codes.
* ``POST /extruder`` — extrude or retract material on a 3D-printer
  extruder axis using relative (``G91``) ``G1 E{dist} F{speed}``
  moves, restoring absolute (``G90``) mode afterwards.

The legacy ``GET /tools`` listing endpoint was superseded by the
base-thread snapshot (``GET /api/v1/base-thread/snapshot``),
which now carries the tool list alongside progress and sensors in
a single 1 Hz round-trip. The :func:`collect_tools` helper lives
in :mod:`modules.tools.service` and is the single source of
truth for the tool payload — this router no longer overlays
runtime state directly.

The router delegates every hardware-touching call to
:func:`get_tools_service` in :mod:`modules.tools.service` — the
router itself does not import ``hardware.*`` so the rule "no
router is allowed to import any hardware file" stays enforced.

The router intentionally has no ``prefix`` argument — the registry
prefixes it when mounting.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from modules.tools.service import get_tools_service

logger = logging.getLogger("backend.modules.tools.router")


# ---------------------------------------------------------------------- #
# Pydantic request models                                                 #
# ---------------------------------------------------------------------- #


class SpindleCommand(BaseModel):
    """Request body for ``POST /spindle``.

    The ``tool_id`` is accepted verbatim and looked up in the active
    ``hardware.json`` ``tools[]`` list — spindles are now an
    inventory (bare ``[spindle]`` → ``spindle_digital``, plus any
    named ``[spindle NAME]`` → ``spindle_digital_NAME``). The
    service raises ``404`` when the id is unknown.

    The optional ``override`` field writes the relative
    ``halui.spindle.override.scale`` pin before every M-code
    dispatch. Defaults to ``1.0`` (the LinuxCNC native default) so
    existing callers keep their behaviour. The range mirrors
    LinuxCNC's documented ``[0.0, 2.0]`` band.
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
    override: float = Field(
        default=1.0,
        ge=0.0,
        le=2.0,
        description=(
            "Relative spindle override (0.0–2.0; 1.0 = 100 %). "
            "Written to halui.spindle.override.scale before each "
            "M-code dispatch when it differs from 1.0."
        ),
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
# Tool target                                                             #
# ---------------------------------------------------------------------- #


class SetToolTargetRequest(BaseModel):
    """Request body for ``POST /tools/{id}/target``.

    The ``tool_id`` field is accepted but ``{id}`` from the URL is
    canonical (same contract as the temperature module's
    ``POST /sensors/{name}/target``). The target range mirrors
    the temperature module's clamp (0–400 °C) since every heating
    tool ends up dispatching ``set_temperature`` under the hood.
    """

    tool_id: str = Field(
        ...,
        min_length=1,
        description="Logical tool identifier (e.g., 'heater_extruder').",
    )
    target: float = Field(
        ...,
        ge=0.0,
        le=400.0,
        description="Target temperature in Celsius (0–400 °C).",
    )


class SetToolTargetResponse(BaseModel):
    """Response body for ``POST /tools/{id}/target``."""

    status: str = Field(
        default="success",
        description="Outcome reported by the hardware layer.",
    )
    tool_id: str = Field(
        ...,
        description="Echo of the tool id from the URL.",
    )
    target: float = Field(
        ...,
        description="Echo of the target value that was applied.",
    )
    sensor: str = Field(
        ...,
        description="Temperature sensor id the value was dispatched to.",
    )


class SpindlePinPayload(BaseModel):
    """Per-pin HAL signal map for one digital spindle.

    Mirrors :class:`backend.modules.tools.config_mapper.SpindlePins`
    as a plain dict for JSON friendliness. ``None`` on any field
    means the integrator did not wire that signal in
    ``hardware.json`` — the dashboard renders an "n/a" cell for
    those.
    """

    id: str
    at_speed: Optional[str] = None
    forward: Optional[str] = None
    reverse: Optional[str] = None
    on: Optional[str] = None
    pwm: Optional[str] = None
    rpm_out: Optional[str] = None
    istop: Optional[str] = None
    estop: Optional[str] = None
    vfd_enable: Optional[str] = None


class SpindleStateResponse(BaseModel):
    """Response body for ``GET /spindle/{tool_id}``.

    Returns the live HAL pin map plus the latest telemetry
    snapshot (``actual`` / ``is_connected`` / ``error_count``) and
    the service-tracked state (``"idle"`` / ``"forward"`` /
    ``"reverse"``). Used for debugging the spindle pipeline from
    ``curl``; the dashboard's :class:`SpindleCard` reads from the
    base-thread snapshot at 1 Hz rather than polling this endpoint.
    """

    id: str = Field(..., description="Spindle tool id (e.g. 'spindle_digital').")
    pins: SpindlePinPayload = Field(
        ..., description="HAL signal map for this spindle."
    )
    state: str = Field(
        ...,
        description='Operator-tracked state: "idle" | "forward" | "reverse".',
    )
    actual: int = Field(
        ..., description="Live RPM feedback (rpm_out pin, or simulated value)."
    )
    is_connected: bool = Field(
        ..., description="VFD engagement flag (on / forward / vfd_enable True)."
    )
    error_count: int = Field(
        ..., description="Cumulative istop / estop count from the VFD."
    )


# ---------------------------------------------------------------------- #
# Endpoints                                                               #
# ---------------------------------------------------------------------- #


# No ``prefix`` — the registry mounts this router under
# ``/api/v1/modules/tools`` and tags it ``modules:tools``.
router = APIRouter(tags=["modules:tools"])


# Allowed action vocabulary. Centralised so the request validators
# below share a single source of truth.
_SPINDLE_ACTIONS = {"forward", "backward", "stop"}
_EXTRUDER_ACTIONS = {"extrude", "retract"}


@router.post(
    "/spindle",
    response_model=ToolCommandResponse,
    summary="Control Spindle",
    description=(
        "Start, reverse, or stop the spindle via the canonical "
        "LinuxCNC M-codes: ``M3 S{speed}`` (forward), "
        "M4 S{speed}`` (backward), or ``M5`` (stop). The router "
        "delegates to :class:`ToolsService.control_spindle`, which "
        "switches the task into MDI mode before dispatching."
    ),
    operation_id="controlSpindle",
)
def control_spindle(cmd: SpindleCommand) -> ToolCommandResponse:
    """Handle a spindle command request."""
    if cmd.action not in _SPINDLE_ACTIONS:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail=f"Invalid spindle action: {cmd.action!r}",
        )

    mdi = get_tools_service().control_spindle(
        cmd.tool_id, cmd.action, cmd.speed, cmd.override
    )
    return ToolCommandResponse(status="success", command=mdi, tool_id=cmd.tool_id)


@router.post(
    "/extruder",
    response_model=ToolCommandResponse,
    description=(
        "Extrude or retract material on the extruder axis. The "
        "router delegates to :class:`ToolsService.control_extruder`, "
        "which switches into relative distance mode (``G91``), "
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
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail=f"Invalid extruder action: {cmd.action!r}",
        )

    move = get_tools_service().control_extruder(
        cmd.tool_id, cmd.action, cmd.distance, cmd.speed
    )
    return ToolCommandResponse(status="success", command=move, tool_id=cmd.tool_id)


# ---------------------------------------------------------------------- #
# Tool target endpoint                                                     #
# ---------------------------------------------------------------------- #


@router.post(
    "/tools/{tool_id}/target",
    response_model=SetToolTargetResponse,
    summary="Set Tool Target Temperature",
    description=(
        "Set the target temperature for a heating tool "
        "(extruder / heated_bed). The router delegates to "
        ":class:`ToolsService.set_tool_target`, which looks up the "
        "tool's ``sensor`` reference and dispatches "
        "``set_temperature`` to the hardware layer."
    ),
    operation_id="setToolTarget",
)
def set_tool_target(
    tool_id: str, req: SetToolTargetRequest
) -> SetToolTargetResponse:
    """Set the target temperature for ``tool_id``."""
    if tool_id != req.tool_id:
        logger.debug(
            "tool_id in body (%r) differs from URL (%r); URL wins",
            req.tool_id,
            tool_id,
        )

    sensor = get_tools_service().set_tool_target(tool_id, req.target)
    return SetToolTargetResponse(
        status="success",
        tool_id=tool_id,
        target=req.target,
        sensor=sensor,
    )


@router.get(
    "/spindle/{tool_id}",
    response_model=SpindleStateResponse,
    summary="Get Spindle State",
    description=(
        "Read the live state + HAL pin map for ``tool_id``. Returns "
        "the canonical ``SpindlePins`` record (as a plain dict), "
        "the live telemetry snapshot (``actual`` / ``is_connected`` "
        "/ ``error_count``), and the current service-tracked state "
        "(``idle`` / ``forward`` / ``reverse``). Useful for "
        "debugging the spindle pipeline from ``curl``; the "
        "dashboard's :class:`SpindleCard` reads from the 1 Hz "
        "base-thread snapshot rather than polling this endpoint."
    ),
    operation_id="getSpindleState",
)
def get_spindle_state(tool_id: str) -> SpindleStateResponse:
    """Return the live spindle state for ``tool_id``."""
    return SpindleStateResponse(**get_tools_service().get_spindle(tool_id))


__all__ = [
    "router",
    "SpindleCommand",
    "ExtruderCommand",
    "ToolCommandResponse",
    "SetToolTargetRequest",
    "SetToolTargetResponse",
]