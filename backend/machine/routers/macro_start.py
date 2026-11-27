"""``POST /api/v1/modules/macros/{name}/start`` — machine-backend half.

The macros URL prefix is shared across the two services: nginx routes
``/api/v1/modules/macros/<name>/start`` to the machine backend
(:8000) and every other macros path to the system service (:8001).
Keep the prefix identical to the system-side macros router so the
frontend contract stays unchanged.
"""
from __future__ import annotations

import logging

from typing import List

from fastapi import APIRouter, Path, Query, Response

from models.MacroModels import MacroKind
from services.program.MacroExecutionService import get_macro_execution_service

logger = logging.getLogger("backend.macro_start_router")

router = APIRouter(
    prefix="/api/v1/modules/macros",
    tags=["modules:macros"],
)


@router.post(
    "/{name}/start",
    status_code=202,
    summary="Start/Execute a macro",
    description=(
        "Starts the requested macro on the CNC machine via the MDI channel "
        "and returns immediately; the lines run in the background and "
        "progress is reported through the console log. "
        "Switches the machine to MDI mode automatically. "
        "For ``.ngc`` subroutines, each ``args`` value is passed as a "
        "positional parameter (``o<name> call [#1] [#2] ...``). "
        "Returns ``400`` if the machine is powered off or in E-STOP, "
        "``409`` if another macro is still running."
    ),
    operation_id="startMacro",
    responses={
        202: {"description": "Macro execution successfully started."},
        404: {"description": "No macro with that name exists on disk."},
        400: {"description": "Invalid name/kind, or machine is not ready (E-STOP/Power Off)."},
        409: {"description": "Another macro is still running."},
    },
)
def start_macro(
    name: str = Path(..., description="Macro name without any extension."),
    kind: str = Query(
        MacroKind.MACRO,
        description="One of ``macro`` / ``ngc`` / ``py`` (``mcode`` cannot be started)."
    ),
    args: List[float] = Query(
        [],
        description="``.ngc``: the subroutine's ``#1``, ``#2``, ...; ``.py``: ``m.args``.",
    ),
) -> Response:
    """Starts the macro via the CNC machine's MDI channel."""
    get_macro_execution_service().start_macro(name, kind, args)
    return Response(status_code=202)


@router.post(
    "/{name}/stop",
    status_code=204,
    summary="Stop the running Python macro",
    description="Ends the running ``.py`` macro's process at once, and aborts a move it started. "
                "``409`` when no Python macro runs.",
    operation_id="stopMacro",
    responses={409: {"description": "No Python macro is running."}},
)
def stop_macro(name: str = Path(..., description="The macro (any name: the running one is stopped).")) -> Response:
    from exceptions import ConflictError

    if not get_macro_execution_service().stop_macro():
        raise ConflictError("No Python macro is running.")
    return Response(status_code=204)
