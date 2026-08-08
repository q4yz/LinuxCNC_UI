"""HTTP router for the macros module.

Mounted by :class:`core.module_registry.ModuleRegistry` under
``/api/v1/modules/macros`` (no router-level ``prefix`` — the
registry adds it). Four endpoints cover the CRUD surface documented
in issue #92:

* ``GET    /``         — ``{"macros": [name, ...]}`` sorted, no
                         extension. Empty list when the storage is
                         empty.
* ``GET    /{name}``   — raw text body (``text/plain``). Returns
                         ``404`` if no macro named ``name`` exists.
* ``PUT    /{name}``   — body is the raw text payload; written
                         atomically; returns ``{"name", "size"}``.
                         ``400`` on invalid names.
* ``DELETE /{name}``   — ``204`` on success, ``404`` on missing.

The router is a thin wrapper over :class:`MacroStorage`; every
filesystem concern (atomic writes, name validation) lives in the
storage layer so future callers (CLI, automation scripts) can use
the same primitives.
"""

from __future__ import annotations

import logging
from typing import Dict, List

from fastapi import APIRouter, Body, HTTPException, Path, Response
from pydantic import BaseModel, Field

from .storage import (
    EXTENSION,
    InvalidMacroNameError,
    MacroNotFoundError,
    MacroStorage,
    default_storage_root,
)

logger = logging.getLogger("backend.modules.macros.router")


# ---------------------------------------------------------------------- #
# Pydantic models                                                         #
# ---------------------------------------------------------------------- #


class MacroListResponse(BaseModel):
    """Response body for ``GET /``."""

    macros: List[str] = Field(
        default_factory=list,
        description=(
            "Macro names (without ``.macro`` extension), sorted "
            "alphabetically."
        ),
    )


class MacroWriteResponse(BaseModel):
    """Response body for ``PUT /{name}``."""

    name: str = Field(..., description="Macro name (without extension).")
    size: int = Field(..., description="Size of the persisted payload in bytes.")


# ---------------------------------------------------------------------- #
# Storage singleton                                                       #
# ---------------------------------------------------------------------- #


# Module-level storage instance, instantiated lazily on first access
# so ``import router`` does not touch the filesystem. The :func:`setup`
# factory in :mod:`.module` does not need to know about this — the
# module class simply returns the router, and the router picks up
# this singleton when the first request lands.
#
# Tests can monkeypatch ``_storage`` with an isolated instance bound
# to a ``tmp_path`` tree so the real ``<repo>/macros/`` directory is
# never touched.
_storage: MacroStorage = MacroStorage(default_storage_root())


# ---------------------------------------------------------------------- #
# Endpoints                                                               #
# ---------------------------------------------------------------------- #


# No ``prefix`` — the registry mounts this router under
# ``/api/v1/modules/macros`` and tags it ``modules:macros``.
router = APIRouter(tags=["modules:macros"])


@router.get(
    "",
    response_model=MacroListResponse,
    summary="List macros",
    description=(
        "Return every macro file under the storage root, sorted "
        "alphabetically. Names are returned without the ``.macro`` "
        "extension so the UI can render them directly."
    ),
    operation_id="listMacros",
)
def list_macros() -> MacroListResponse:
    """Return the list of persisted macro names."""
    return MacroListResponse(macros=_storage.list())


@router.get(
    "/{name}",
    summary="Read macro",
    description=(
        "Return the raw text payload of ``<name>.macro``. The "
        "response body is the file contents verbatim (no JSON "
        "wrapping). Returns ``404`` when no such macro exists."
    ),
    operation_id="readMacro",
    response_class=Response,
    responses={
        200: {
            "description": "Raw macro payload.",
            "content": {"text/plain": {}},
        },
        404: {"description": "No macro with that name."},
    },
)
def read_macro(
    name: str = Path(..., description="Macro name without the .macro extension."),
) -> Response:
    """Return the raw text content of a single macro."""
    try:
        content = _storage.read(name)
    except InvalidMacroNameError as exc:
        # Treat invalid names the same as missing files so the
        # router does not leak storage-layer vocabulary to callers.
        raise HTTPException(status_code=404, detail=str(exc))
    except MacroNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return Response(content=content, media_type="text/plain")


@router.put(
    "/{name}",
    response_model=MacroWriteResponse,
    summary="Create or overwrite a macro",
    description=(
        "Persist the request body to ``<name>.macro``. Writes are "
        "atomic (``tempfile`` + ``os.replace``) so a crash mid-write "
        "never leaves a half-written file. Returns ``400`` when "
        "``name`` fails validation, ``200`` on success with the "
        "stored ``name`` and byte ``size``."
    ),
    operation_id="writeMacro",
)
def write_macro(
    name: str = Path(..., description="Macro name without the .macro extension."),
    content: str = Body(
        ...,
        media_type="text/plain",
        description="Raw macro payload (any text content).",
    ),
) -> MacroWriteResponse:
    """Persist the supplied text payload under ``name``."""
    try:
        size = _storage.write(name, content)
    except InvalidMacroNameError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return MacroWriteResponse(name=name, size=size)


@router.delete(
    "/{name}",
    status_code=204,
    summary="Delete a macro",
    description=(
        "Remove ``<name>.macro`` from the storage root. Returns "
        "``204`` on success and ``404`` when no such macro exists."
    ),
    operation_id="deleteMacro",
    responses={
        204: {"description": "Macro deleted."},
        404: {"description": "No macro with that name."},
    },
)
def delete_macro(
    name: str = Path(..., description="Macro name without the .macro extension."),
) -> Response:
    """Delete the named macro from disk."""
    try:
        _storage.delete(name)
    except InvalidMacroNameError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except MacroNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return Response(status_code=204)


__all__ = [
    "router",
    "MacroListResponse",
    "MacroWriteResponse",
    "EXTENSION",
]
