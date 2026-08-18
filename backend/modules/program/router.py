"""Program lifecycle HTTP router.

Hosts the program endpoints that used to live in
``routers/machine.py`` (run / stop / pause / resume / parse / load).
The router is mounted by the registry under
``/api/v1/modules/program``.

The lifecycle mirrors LinuxCNC's canonical two-step flow:

1. ``POST /load {filename}`` calls ``command.program_open(path)``
   which sets ``stat.file`` while leaving ``interp_state`` at
   ``INTERP_IDLE``. The "loaded" state is implicit (file is set,
   interpreter is idle) — see :func:`hardware.linuxcnc_mock.is_program_loaded`
   for the predicate and ``hardware.connection.get_machine_stat``
   for the canonical read surface.

   On real LinuxCNC ``program_open`` is asynchronous: the call
   returns immediately but the interpreter needs a few NML ticks
   to actually populate ``stat.file``. We therefore pass a non-zero
   ``cmd_timeout`` to :func:`hardware.connection.execute_sync_cmd`
   (so ``wait_complete`` blocks until the command is processed) and
   additionally poll ``stat.file`` until it matches the requested
   path — the same pattern the upstream LinuxCNC Python example
   documents. If the file does not appear within the budget we
   raise ``504 Gateway Timeout`` so the operator knows the load
   never landed.
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


from services.domain_file_services import get_program_service
from services.line_count_cache import (
    count_lines,
    register as register_line_count,
    unregister_all as clear_line_count_cache,
)
from modules.program.service import get_program_lifecycle_service
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
    "/load",
    response_model=StatusResponse,
    operation_id="loadProgram",
)
def load_program(payload: LoadProgramRequest):
    service = get_program_service()

    try:
        target = service.safe_join(payload.filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if not target.exists():
        raise HTTPException(status_code=404, detail="G-code file not found.")

    try:
        get_program_lifecycle_service().load_program(str(target))
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc))

    register_line_count(str(target), count_lines(str(target)))
    return StatusResponse(status="success")


@router.post(
    "/run",
    response_model=StatusResponse,
    operation_id="runProgram",
)
def run_program(line_number: int = 0):
    try:
        get_program_lifecycle_service().start_program(line_number)
        return StatusResponse(status="success")
    except RuntimeError as exc:
        # Translate the service's pure python error to HTTP 409 Conflict
        raise HTTPException(status_code=409, detail=str(exc))


@router.post(
    "/stop",
    response_model=StatusResponse,
    operation_id="stopProgram",
)
def stop_program():
    get_program_lifecycle_service().stop_program()
    return StatusResponse(status="success")


@router.post(
    "/unload",
    response_model=StatusResponse,
    operation_id="unloadProgram",
)
def unload_program():
    service = get_program_service()
    target = service.safe_join("EmptyProgram.ngc")

    try:
        get_program_lifecycle_service().load_program(str(target))
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc))

    clear_line_count_cache()
    return StatusResponse(status="success")


@router.post(
    "/pause",
    response_model=StatusResponse,
    operation_id="pauseProgram",
)
def pause_program():
    get_program_lifecycle_service().pause_program()
    return StatusResponse(status="success")


@router.post(
    "/resume",
    response_model=StatusResponse,
    operation_id="resumeProgram",
)
def resume_program():
    get_program_lifecycle_service().resume_program()
    return StatusResponse(status="success")

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
    "unload_program",
    "pause_program",
    "resume_program",
    "trigger_parser",
    "load_program",
    "StatusResponse",
    "ParseResponse",
    "LoadProgramRequest",
]
