"""``POST /api/v1/modules/macros/{name}/start`` — machine-backend half.

The macros URL prefix is shared across the two services: nginx routes
``/api/v1/modules/macros/<name>/start`` to the machine backend
(:8000) and every other macros path to the system service (:8001).
Keep the prefix identical to the system-side macros router so the
frontend contract stays unchanged.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Path, Query, Response

from services.MacroExecutionService import (
    MacroKind,
    get_macro_execution_service,
)

logger = logging.getLogger("backend.macro_start_router")

router = APIRouter(
    prefix="/api/v1/modules/macros",
    tags=["modules:macros"],
)


@router.post(
    "/{name}/start",
    status_code=204,
    summary="Start/Execute a macro",
    description=(
        "Executes the requested macro on the CNC machine via the MDI channel. "
        "Switches the machine to MDI mode automatically. "
        "Returns ``400`` if the machine is powered off or in E-STOP."
    ),
    operation_id="startMacro",
    responses={
        204: {"description": "Macro execution successfully started."},
        404: {"description": "No macro with that name exists on disk."},
        400: {"description": "Invalid name/kind, or machine is not ready (E-STOP/Power Off)."},
    },
)
def start_macro(
    name: str = Path(..., description="Macro name without any extension."),
    kind: str = Query(
        MacroKind.MACRO,
        description="One of ``macro`` / ``ngc`` / ``mcode``."
    ),
) -> Response:
    """Executes the macro via the CNC machine's MDI channel."""
    get_macro_execution_service().start_macro(name, kind)
    return Response(status_code=204)
