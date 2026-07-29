"""Program lifecycle HTTP router.

Hosts the program endpoints that used to live in
``routers/machine.py`` (run / stop / pause / resume / parse). The
router is mounted by the registry under
``/api/v1/modules/program``.

Behavior mirrors the legacy implementation exactly so any external
operator scripts keep working — only the URL prefix changes (see
issue #38 § 6 Risk #7). The dedicated UI for this module lands in
Phase 3 per the roadmap; this issue only moves the HTTP surface so
:file:`routers/machine.py` can be deleted.
"""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter
from pydantic import BaseModel, Field

from hardware import execute_sync_cmd, linuxcnc

logger = logging.getLogger("backend.modules.program.router")


class StatusResponse(BaseModel):
    """Generic response model for endpoints that return a status string."""

    status: str = Field(
        ...,
        description=(
            "Outcome reported by the hardware layer (e.g., 'success')"
        ),
    )


class ParseResponse(BaseModel):
    """Response model for the Klipper-to-LinuxCNC parser trigger."""

    status: str = Field(..., description="Outcome of the parser trigger")
    message: str = Field(..., description="Human-readable status message")


router = APIRouter(tags=["Program Control"])


@router.post(
    "/run",
    summary="Run Program",
    description=(
        "Start or resume the loaded G-code program from a specific "
        "line."
    ),
    operation_id="runProgram",
    response_model=StatusResponse,
)
def run_program(line_number: int = 0) -> StatusResponse:
    """Start the loaded G-code program."""
    execute_sync_cmd("mode", 3, getattr(linuxcnc, "MODE_AUTO", 2))
    result = execute_sync_cmd(
        "auto", 0, getattr(linuxcnc, "AUTO_RUN", 0), line_number
    )
    return StatusResponse(status=result.get("status", "success"))


@router.post(
    "/stop",
    summary="Stop Program",
    description="Stop/abort the currently running program.",
    operation_id="stopProgram",
    response_model=StatusResponse,
)
def stop_program() -> StatusResponse:
    """Stop/abort the currently running program."""
    result = execute_sync_cmd("abort")
    return StatusResponse(status=result.get("status", "success"))


@router.post(
    "/pause",
    summary="Pause Program",
    description="Pause the currently running program.",
    operation_id="pauseProgram",
    response_model=StatusResponse,
)
def pause_program() -> StatusResponse:
    """Pause the currently running program."""
    result = execute_sync_cmd(
        "auto", 0, getattr(linuxcnc, "AUTO_PAUSE", 1)
    )
    return StatusResponse(status=result.get("status", "success"))


@router.post(
    "/resume",
    summary="Resume Program",
    description="Resume a paused program.",
    operation_id="resumeProgram",
    response_model=StatusResponse,
)
def resume_program() -> StatusResponse:
    """Resume a paused program."""
    result = execute_sync_cmd(
        "auto", 0, getattr(linuxcnc, "AUTO_RESUME", 2)
    )
    return StatusResponse(status=result.get("status", "success"))


@router.post(
    "/parse",
    summary="Trigger Parser",
    description=(
        "Manually trigger the Klipper-to-LinuxCNC configuration "
        "parser."
    ),
    operation_id="triggerParser",
    response_model=ParseResponse,
)
def trigger_parser() -> ParseResponse:
    """Trigger the parser (mocked as a 1 s delay in v1)."""
    logger.info("Triggering Klipper-to-LinuxCNC parser...")
    time.sleep(1)  # mock delay
    return ParseResponse(status="success", message="Parsing complete")


__all__ = [
    "router",
    "run_program",
    "stop_program",
    "pause_program",
    "resume_program",
    "trigger_parser",
    "StatusResponse",
    "ParseResponse",
]
