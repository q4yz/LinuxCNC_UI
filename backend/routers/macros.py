"""HTTP surface for the macro subsystem (issue #7).

Endpoints:

* ``GET    /api/macros``              — list all macros.
* ``GET    /api/macros/{name}``       — fetch a single macro's content.
* ``PUT    /api/macros/{name}``       — upsert a macro.
* ``DELETE /api/macros/{name}``       — delete a macro.
* ``POST   /api/macros/{name}/run``   — execute a macro.

The router is mounted by ``backend/main.py`` via
``app.include_router(macros.router)``. Errors are translated into
actionable HTTP statuses; Python exceptions raised during a run
are surfaced as ``ok: false`` responses rather than 500s so the
editor can render the traceback.

A tiny ``probe_grid.macro`` example is seeded on first boot when
the macros directory is empty. The seeder is opt-in via the
``MACROS_SEED_EXAMPLES`` environment variable (default: enabled)
and never overwrites an existing file.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import List

from fastapi import APIRouter, HTTPException

from core.macro_models import (
    MacroContent,
    MacroRunResponse,
    MacroSaveRequest,
    MacroSummary,
)
from services.macro_executor import execute_macro
from services.macro_parser import validate_macro_name
from services.macro_storage import MacroStorage

logger = logging.getLogger("backend.routers.macros")

router = APIRouter(prefix="/api/macros", tags=["Macros"])

# Module-level singleton: ``include_router`` is called once at
# startup, and the storage instance is cheap to construct.
_storage = MacroStorage()


# ---------------------------------------------------------------------- #
# Seeding                                                                #
# ---------------------------------------------------------------------- #


_SEED_PROBE_GRID = """\
; probe_grid.macro
;
; Demonstrates the hybrid G-code + Python language. Everything
; outside ``{ ... }`` is G-code sent to LinuxCNC; everything
; inside ``{ ... }`` is executed as Python with a ``cnc`` object
; that mirrors the LinuxCNC command interface.

G21 ; Set units to mm
G90 ; Absolute positioning
G0 Z10 ; Move safely above workpiece

{
    # 'cnc' is injected by the backend. It exposes:
    #   cnc.emit("G0 X0 Y0")      -> send G-code to the controller
    #   cnc.log("...")            -> log to the editor console
    #   cnc.warn("...")           -> log as a warning
    #   cnc.get_pos()             -> read current head position
    grid_size = 3
    spacing = 15.0
    for x in range(grid_size):
        for y in range(grid_size):
            x_pos = x * spacing
            y_pos = y * spacing
            cnc.emit(f"G0 X{x_pos} Y{y_pos}")
            cnc.emit("G38.2 Z-5 F100 ; Probe down")
            cnc.emit("G0 Z10 ; Retract")
            cnc.log(f"Probed point {x}, {y}")
}

G0 X0 Y0
M2 ; End program
"""


def _seed_examples() -> None:
    """Write ``probe_grid.macro`` to the macros directory on first boot."""
    flag = os.environ.get("MACROS_SEED_EXAMPLES", "1").lower()
    if flag in {"0", "false", "no", "off"}:
        logger.info("macros: example seeding disabled (MACROS_SEED_EXAMPLES=%s)", flag)
        return

    if not _storage.list():
        try:
            _storage.write("probe_grid", _SEED_PROBE_GRID)
            logger.info("macros: seeded probe_grid.macro")
        except Exception as exc:  # noqa: BLE001 - defensive
            logger.warning("macros: failed to seed example: %s", exc)


_seed_examples()


# ---------------------------------------------------------------------- #
# Routes                                                                 #
# ---------------------------------------------------------------------- #


@router.get(
    "",
    summary="List Macros",
    description=(
        "Return one entry per ``.macro`` file under the configured "
        "macros directory. The response is the small summary view "
        "the dashboard grid uses; the editor fetches the full "
        "content on demand via ``GET /api/macros/{name}``."
    ),
    operation_id="listMacros",
    response_model=List[MacroSummary],
)
def list_macros() -> List[MacroSummary]:
    """List every macro on disk."""
    return [
        MacroSummary(
            name=entry.name,
            modified=entry.modified,
            size=entry.size,
        )
        for entry in _storage.list()
    ]


@router.get(
    "/{name}",
    summary="Get Macro Content",
    description=(
        "Return the raw text content of a single macro. The editor "
        "view uses this endpoint to populate the CodeMirror "
        "backing model when the user picks a file."
    ),
    operation_id="getMacro",
    response_model=MacroContent,
)
def get_macro(name: str) -> MacroContent:
    """Fetch a single macro by name."""
    try:
        content = _storage.read(name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Macro not found.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    canonical = validate_macro_name(name)
    try:
        stat = (_storage.root / canonical).stat()
        modified = datetime.fromtimestamp(stat.st_mtime).isoformat()
    except OSError:
        modified = ""
    return MacroContent(name=canonical, content=content, modified=modified)


@router.put(
    "/{name}",
    summary="Save Macro",
    description=(
        "Create or overwrite a macro. The ``content`` field is the "
        "full file body; the backend normalises the extension and "
        "writes atomically."
    ),
    operation_id="saveMacro",
    response_model=MacroContent,
)
def save_macro(name: str, payload: MacroSaveRequest) -> MacroContent:
    """Persist ``payload.content`` to ``name``."""
    try:
        canonical = _storage.write(name, payload.content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        logger.error("save_macro: write failed for %s: %s", name, exc)
        raise HTTPException(status_code=500, detail="Failed to save macro.") from exc

    try:
        stat = (_storage.root / canonical).stat()
        modified = datetime.fromtimestamp(stat.st_mtime).isoformat()
    except OSError:
        modified = ""
    return MacroContent(
        name=canonical,
        content=payload.content,
        modified=modified,
    )


@router.delete(
    "/{name}",
    summary="Delete Macro",
    description="Remove a macro file from disk. Idempotent; missing files are no-ops.",
    operation_id="deleteMacro",
    response_model=dict,
)
def delete_macro(name: str) -> dict:
    """Delete a macro."""
    try:
        canonical = validate_macro_name(name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    path = _storage.root / canonical
    if path.exists():
        try:
            path.unlink()
        except OSError as exc:
            logger.error("delete_macro: unlink failed for %s: %s", path, exc)
            raise HTTPException(status_code=500, detail="Failed to delete macro.") from exc
    return {"status": "success", "name": canonical}


@router.post(
    "/{name}/run",
    summary="Run Macro",
    description=(
        "Execute a macro by name. The backend reads the file from "
        "disk, parses it, and walks the resulting blocks. G-code "
        "lines are streamed to LinuxCNC; Python blocks are executed "
        "with a curated ``globals()`` dict that exposes ``cnc``, "
        "``math``, and the built-ins."
    ),
    operation_id="runMacro",
    response_model=MacroRunResponse,
)
async def run_macro(name: str) -> MacroRunResponse:
    """Execute ``name`` and return a structured run response."""
    try:
        content = _storage.read(name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Macro not found.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    response = await execute_macro(content)
    # Even on failure we return ``200`` because the structured
    # ``ok: false`` payload is the canonical "run finished but
    # produced an error" contract.
    return response


__all__ = ["router"]
