"""Program lifecycle HTTP router.

Hosts the program endpoints that used to live in
``routers/machine.py`` (run / stop / pause / resume / parse / load).
The router is mounted by the registry under
``/api/v1/modules/program``.

The lifecycle mirrors LinuxCNC's canonical two-step flow:

1. ``POST /load {filename}`` calls ``command.program_open(path)``
   which sets ``stat.file`` while leaving ``interp_state`` at
   ``INTERP_IDLE``. The "loaded" state is implicit (file is set,
   interpreter is idle) — see :func:`hardware.linuxcnc_mock.is_program_loaded`.
2. ``POST /run`` calls ``auto(AUTO_RUN, line)`` which flips
   ``interp_state`` to ``INTERP_READING``. The endpoint refuses
   with ``409 Conflict`` when no file has been loaded so the
   frontend cannot accidentally start the interpreter on an empty
   program.

The dedicated UI for this module lands in Phase 3 per the roadmap;
this router is the contract that backs the dashboard widget's
"Loaded" branch.
"""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from hardware import execute_sync_cmd, linuxcnc, linuxcnc_mock
from services import get_program_service

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


router = APIRouter(tags=["modules:program"])

class LoadProgramRequest(BaseModel):
    filename: str




@router.post(
    "/run",
    summary="Run Program",
    description=(
        "Start or resume the loaded G-code program from a specific "
        "line. Requires ``POST /load`` to have been called first "
        "with a valid filename; otherwise returns ``409 Conflict``."
    ),
    operation_id="runProgram",
    response_model=StatusResponse,
)
def run_program(line_number: int = 0) -> StatusResponse:
    """Start the loaded G-code program.

    Mirrors LinuxCNC's two-step contract: the ``program_open`` call
    (handled by ``POST /load``) must have set ``stat.file`` before
    the interpreter can be told to start. Without a loaded file we
    return ``409 Conflict`` so the frontend can surface a clear
    "no program loaded" message instead of the interpreter silently
    reading nothing.
    """
    if not linuxcnc_mock.is_program_loaded():
        raise HTTPException(
            status_code=409,
            detail="No program loaded. Call POST /load first.",
        )
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


@router.post(
    "/load",
    summary="Load G-Code Program",
    description=(
        "Open a previously uploaded G-code file in the LinuxCNC "
        "interpreter. The file must live under the upload root "
        "served by ``routers/files.py``; returns ``404`` if the "
        "filename is unknown and ``400`` if the path fails the "
        "``safe_join`` invariant. After this call succeeds the "
        "program is in the loaded state (``stat.file`` set, "
        "``interp_state`` is ``INTERP_IDLE``); the next "
        "``POST /run`` starts it."
    ),
    operation_id="loadProgram",
    response_model=StatusResponse,
)
def load_program(payload: LoadProgramRequest) -> StatusResponse:
    """Open a G-code file in the interpreter (the load step).

    The filename is validated against the upload root using
    :meth:`ProgramFileService.safe_join` so a client cannot ask the
    mock to open an arbitrary path on disk. The forward to
    ``program_open`` is fire-and-forget — the mock updates
    ``_machine_state.file`` / ``current_line`` / ``total_lines``
    and the WebSocket telemetry loop surfaces the new state on the
    next tick.
    """
    logger.info("Loading G-code program: %s", payload.filename)

    service = get_program_service()
    try:
        target = service.safe_join(payload.filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not target.exists():
        raise HTTPException(
            status_code=404,
            detail=f"G-code file '{payload.filename}' not found in upload root",
        )

    execute_sync_cmd("program_open", 0, str(target))
    return StatusResponse(status="success")


__all__ = [
    "router",
    "run_program",
    "stop_program",
    "pause_program",
    "resume_program",
    "trigger_parser",
    "load_program",
    "StatusResponse",
    "ParseResponse",
    "LoadProgramRequest",
]
