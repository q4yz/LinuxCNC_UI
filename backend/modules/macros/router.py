"""HTTP router for the macros module.

Mounted by :class:`core.module_registry.ModuleRegistry` under
``/api/v1/modules/macros`` (no router-level ``prefix`` — the
registry adds it). The router fronts two storage back-ends:

* :class:`backend.modules.macros.storage.MacroStorage` — handles
  ``.macro`` and ``.ngc`` files in ``<repo>/macros/``.
* :class:`backend.services.domain_file_services.MCodeFileService`
  — handles bare ``M<num>`` files in ``<repo>/machine_config/m_codes/``.

The router exposes a uniform ``?kind=`` query parameter so a
single endpoint family covers all three storage surfaces. Every
endpoint accepts ``kind`` ∈ ``{"macro", "ngc", "mcode"}`` and
dispatches accordingly.

Endpoints
---------

* ``GET    /``               — list macro entries of the requested
                              ``kind``. Returns
                              ``{"macros": [{"name", "kind",
                              "size_bytes"}]}``.
* ``GET    /{name}?kind=``   — raw text payload of the macro file.
                              ``404`` for missing, ``400`` for an
                              out-of-range name.
* ``PUT    /{name}?kind=``   — create or overwrite the macro file.
                              Atomic write (``tempfile`` +
                              ``os.replace``); empty body → ``422``
                              for ``macro`` / ``ngc`` (FastAPI's
                              raw-body quirk the frontend mirrors
                              with the ``"\n"`` sentinel).
* ``DELETE /{name}?kind=``   — ``204`` on success, ``404`` on
                              missing.

M-code name validation lives at the router level (regex
``^M1\\d{2}$`` — M100..M199 inclusive); the
:class:`MCodeFileService`'s listing filter enforces the same range
when reading, so the regex and the listing stay in lockstep.
"""

from __future__ import annotations

import logging
import re
from typing import List

from fastapi import APIRouter, Body, Path, Query, Response
from pydantic import BaseModel, Field

from exceptions import BadRequestError, NotFoundError
from services import get_mcode_service
from services.domain_file_services import FileMetadata

from .storage import (
    EXTENSION,
    InvalidMacroKindError,
    InvalidMacroNameError,
    MacroKind,
    MacroNotFoundError,
    MacroStorage,
    default_storage_root,
)

logger = logging.getLogger("backend.modules.macros.router")

#: Mirrors ``MCodeFileService.MCODE_NAME``. Kept here so the router's
#: 400 messages are tight without pulling the service module.
_MCODE_RE = re.compile(r"^M1\d{2}$")


# ---------------------------------------------------------------------- #
# Pydantic models                                                         #
# ---------------------------------------------------------------------- #


VALID_KINDS = (MacroKind.MACRO, MacroKind.NGC, MacroKind.MCODE)


class MacroListItem(BaseModel):
    """One row of the unified macro listing.

    Attributes:
        name: File name without the ``.macro`` / ``.ngc`` suffix.
            For ``mcode``, the bare ``M<num>`` token (already
            extension-free).
        kind: One of ``"macro"`` / ``"ngc"`` / ``"mcode"``.
        size_bytes: On-disk byte size, used by the dashboard so the
            editor modal knows whether to skip a re-fetch.
    """

    name: str = Field(..., description="File name without extension.")
    kind: str = Field(..., description="One of macro / ngc / mcode.")
    size_bytes: int = Field(..., description="On-disk byte size.")


class MacroListResponse(BaseModel):
    """Response body for ``GET /``.

    The :class:`MacroListItem` rows are sorted alphabetically by name
    so the dashboard renders deterministically without a client-side
    sort.
    """

    macros: List[MacroListItem] = Field(
        default_factory=list,
        description=(
            "Macro entries of the requested kind, sorted by name. "
            "Each item carries the kind tag so the frontend can "
            "render a single flat list across multiple kinds."
        ),
    )


class MacroWriteResponse(BaseModel):
    """Response body for ``PUT /{name}?kind=``."""

    name: str = Field(..., description="File name (no extension).")
    kind: str = Field(..., description="One of macro / ngc / mcode.")
    size: int = Field(..., description="Size of the persisted payload in bytes.")


class MacroContentPayload(BaseModel):
    """Body of ``PUT /{name}/content?kind=`` (universal-editor envelope).

    The :class:`backend.modules.macros.storage.MacroStorage` write path
    is line-oriented; ``content`` is decoded UTF-8 and persisted as-is.
    Empty payloads are normalised to a single newline so FastAPI's
    ``text/plain`` body validation (which rejects ``""`` with ``422``)
    is bypassed the same way the other universal-editor sources do it.
    """

    content: str = Field(..., description="Raw macro payload (UTF-8 text).")


class MacroContentResponse(BaseModel):
    """Response body of ``GET/PUT /{name}/content?kind=`` (universal-editor envelope).

    Mirrors the shape the editor store expects from every other
    source (``profiles`` / ``m_codes`` / ``programs``) so the
    universal editor's ``source``-driven dispatch can plug macros in
    without branching on response shape.
    """

    name: str = Field(..., description="File name (no extension).")
    kind: str = Field(..., description="One of macro / ngc / mcode.")
    content: str = Field(..., description="Raw text content of the file.")
    size_bytes: int = Field(..., description="On-disk byte size.")


# ---------------------------------------------------------------------- #
# Storage singletons                                                      #
# ---------------------------------------------------------------------- #


# Module-level storage instance, instantiated lazily on first access
# so ``import router`` does not touch the filesystem. The :func:`setup`
# factory in :mod:`.module` does not need to know about this — the
# module class simply returns the router, and the router picks up
# this singleton when the first request lands.
#
# Tests can monkeypatch ``_macro_storage`` with an isolated instance
# bound to a ``tmp_path`` tree so the real ``<repo>/macros/`` directory
# is never touched.
_macro_storage: MacroStorage = MacroStorage(default_storage_root())


# ---------------------------------------------------------------------- #
# Helpers                                                                 #
# ---------------------------------------------------------------------- #


def _validate_kind(kind: str) -> str:
    """Return ``kind`` if it is part of :data:`VALID_KINDS`.

    Raises:
        HTTPException: ``400`` when the kind is unknown.
    """
    if kind not in VALID_KINDS:
        raise BadRequestError(
            f"unknown macro kind: {kind!r}; expected one of {VALID_KINDS}",
        )
    return kind


def _validate_mcode_name(name: str) -> str:
    """Return ``name`` if it falls in ``M100..M199`` inclusive.

    Raises:
        HTTPException: ``400`` for an out-of-range name.
    """
    if not _MCODE_RE.match(name):
        raise BadRequestError(
            f"invalid M-code name: {name!r} "
            "(must match ^M1\\d{2}$ — i.e. M100..M199)"
        )
    return name


def _storage_size(name: str, kind: str) -> int:
    """Return the on-disk byte size for a macro entry."""
    if kind == MacroKind.MCODE:
        service = get_mcode_service()
        entry = FileMetadata(
            name=name, path=name, parent="", kind="file", size_bytes=0,
            modified=None, read_only=False,
        )
        # The :class:`FileService.list_files` walker hits the
        # :class:`MCodeFileService.mcode_filter`, so a too-large
        # name returns nothing. ``MCODE_NAME`` already validated the
        # value at the router boundary.
        for existing in service.list_files():
            if existing.name == name:
                return existing.size_bytes
        return 0
    # macro / ngc — MacroStorage owns the disk root.
    try:
        return _macro_storage.size(name, kind=kind)
    except (InvalidMacroNameError, InvalidMacroKindError):
        return 0


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
        "Return every macro file of the requested ``kind``, sorted "
        "alphabetically by name. The frontend uses a single flat "
        "list to render both kinds, so each entry carries the "
        "kind tag."
    ),
    operation_id="listMacros",
)
def list_macros(
    kind: str = Query(
        MacroKind.MACRO,
        description="One of ``macro`` / ``ngc`` / ``mcode``.",
    ),
) -> MacroListResponse:
    """Return the list of persisted macro entries of ``kind``."""
    _validate_kind(kind)
    if kind == MacroKind.MCODE:
        service = get_mcode_service()
        entries = service.list_files()
        items = [
            MacroListItem(
                name=entry.name,
                kind=MacroKind.MCODE,
                size_bytes=entry.size_bytes,
            )
            for entry in entries
            if entry.kind == "file"
        ]
    else:
        names = _macro_storage.list(kind=kind)
        items = [
            MacroListItem(
                name=name,
                kind=kind,
                size_bytes=_storage_size(name, kind),
            )
            for name in names
        ]
    items.sort(key=lambda item: item.name)
    return MacroListResponse(macros=items)


@router.get(
    "/{name}",
    summary="Read macro",
    description=(
        "Return the raw text payload of the requested macro. For "
        "``mcode``, ``name`` is the bare ``M<num>`` token. The "
        "response body is the file contents verbatim (no JSON "
        "wrapping). Returns ``404`` when no such macro exists and "
        "``400`` when the name / kind fails validation."
    ),
    operation_id="readMacro",
    response_class=Response,
    responses={
        200: {
            "description": "Raw macro payload.",
            "content": {"text/plain": {}},
        },
        404: {"description": "No macro with that name."},
        400: {"description": "Invalid name or kind."},
    },
)
def read_macro(
    name: str = Path(..., description="Macro name without any extension."),
    kind: str = Query(
        MacroKind.MACRO,
        description="One of ``macro`` / ``ngc`` / ``mcode``.",
    ),
) -> Response:
    """Return the raw text content of a single macro."""
    _validate_kind(kind)
    if kind == MacroKind.MCODE:
        _validate_mcode_name(name)
        service = get_mcode_service()
        try:
            target = service.safe_join(name)
        except ValueError as exc:
            raise BadRequestError(str(exc))
        if not target.exists():
            raise NotFoundError(f"M-code not found: {name}")
        return Response(content=target.read_text(encoding="utf-8"), media_type="text/plain")

    try:
        content = _macro_storage.read(name, kind=kind)
    except InvalidMacroNameError as exc:
        # Storage raises ``InvalidMacroNameError`` for path-traversal
        # attempts (``..`` etc.) so treat them as not-found at the HTTP
        # boundary — they carry no useful payload for the operator.
        raise NotFoundError(str(exc))
    except InvalidMacroKindError as exc:
        raise BadRequestError(str(exc))
    except MacroNotFoundError as exc:
        raise NotFoundError(str(exc))
    return Response(content=content, media_type="text/plain")


@router.put(
    "/{name}",
    response_model=MacroWriteResponse,
    summary="Create or overwrite a macro",
    description=(
        "Persist the request body to the requested kind's file. "
        "Writes are atomic (``tempfile`` + ``os.replace``) so a "
        "crash mid-write never leaves a half-written file. "
        "Returns ``400`` when ``name`` / ``kind`` fails "
        "validation, ``422`` for ``macro`` / ``ngc`` with an "
        "empty body, and ``200`` on success with the stored "
        "``name``, ``kind``, and byte ``size``."
    ),
    operation_id="writeMacro",
)
def write_macro(
    name: str = Path(..., description="Macro name without any extension."),
    kind: str = Query(
        MacroKind.MACRO,
        description="One of ``macro`` / ``ngc`` / ``mcode``.",
    ),
    content: str = Body(
        ...,
        media_type="text/plain",
        description="Raw macro payload (any text content).",
    ),
) -> MacroWriteResponse:
    """Persist the supplied text payload under ``name`` of ``kind``."""
    _validate_kind(kind)
    if kind == MacroKind.MCODE:
        _validate_mcode_name(name)
        service = get_mcode_service()
        try:
            service.write_file(name, content)
        except ValueError as exc:
            raise BadRequestError(str(exc))
        # :meth:`FileService.write_file` returns ``None`` for
        # parity with the stdlib ``Path.write_text`` family; size
        # is computed via :meth:`safe_join` + ``stat``.
        target = service.safe_join(name)
        size = target.stat().st_size if target.exists() else 0
        return MacroWriteResponse(name=name, kind=MacroKind.MCODE, size=size)
    try:
        size = _macro_storage.write(name, content, kind=kind)
    except InvalidMacroNameError as exc:
        raise BadRequestError(str(exc))
    except InvalidMacroKindError as exc:
        raise BadRequestError(str(exc))
    return MacroWriteResponse(name=name, kind=kind, size=size)


@router.delete(
    "/{name}",
    status_code=204,
    summary="Delete a macro",
    description=(
        "Remove the named macro from disk. Returns ``204`` on "
        "success and ``404`` when no such macro exists."
    ),
    operation_id="deleteMacro",
    responses={
        204: {"description": "Macro deleted."},
        404: {"description": "No macro with that name."},
        400: {"description": "Invalid name or kind."},
    },
)
def delete_macro(
    name: str = Path(..., description="Macro name without any extension."),
    kind: str = Query(
        MacroKind.MACRO,
        description="One of ``macro`` / ``ngc`` / ``mcode``.",
    ),
) -> Response:
    """Delete the named macro from disk."""
    _validate_kind(kind)
    if kind == MacroKind.MCODE:
        _validate_mcode_name(name)
        service = get_mcode_service()
        try:
            target = service.safe_join(name)
        except ValueError as exc:
            raise BadRequestError(str(exc))
        if not target.exists():
            raise NotFoundError(f"M-code not found: {name}")
        target.unlink()
        return Response(status_code=204)

    try:
        _macro_storage.delete(name, kind=kind)
    except InvalidMacroNameError as exc:
        raise NotFoundError(str(exc))
    except InvalidMacroKindError as exc:
        raise BadRequestError(str(exc))
    except MacroNotFoundError as exc:
        raise NotFoundError(str(exc))
    return Response(status_code=204)


# ---------------------------------------------------------------------- #
# Universal-editor content endpoints                                       #
# ---------------------------------------------------------------------- #
#
# The legacy ``/{name}?kind=`` endpoints above return raw ``text/plain``
# bodies, which is incompatible with the universal editor's source-
# driven dispatch (every other source — ``profiles``, ``m_codes``,
# ``programs`` — returns a JSON envelope). These new endpoints expose
# the same read/write surface in the editor's contract:
#
#     GET  /{name}/content?kind=macro  →  {"name", "kind", "content", "size_bytes"}
#     PUT  /{name}/content?kind=macro  →  same envelope, post-write
#
# They are NOT a back-compat shim — the universal editor never reads
# the legacy endpoints and the macros dashboard module does not need
# them either. The two surfaces coexist; the editor only ever calls
# the ``/content`` family.


@router.get(
    "/{name}/content",
    summary="Read macro content (universal-editor envelope)",
    description=(
        "Return the requested macro as a JSON envelope of the shape "
        "the universal editor's source-driven dispatch expects: "
        "``{name, kind, content, size_bytes}``. Mirrors the contract "
        "every other source (``profiles``, ``m_codes``, ``programs``) "
        "already satisfies. Returns ``404`` when the file is missing, "
        "``400`` for an invalid name or kind."
    ),
    operation_id="readMacroContent",
    response_model=MacroContentResponse,
    responses={
        404: {"description": "No macro with that name."},
        400: {"description": "Invalid name or kind."},
    },
)
def read_macro_content(
    name: str = Path(..., description="Macro name without any extension."),
    kind: str = Query(
        MacroKind.MACRO,
        description="One of ``macro`` / ``ngc`` / ``mcode``.",
    ),
) -> MacroContentResponse:
    """Read a macro and return the universal-editor envelope shape."""
    _validate_kind(kind)
    if kind == MacroKind.MCODE:
        _validate_mcode_name(name)
        service = get_mcode_service()
        try:
            target = service.safe_join(name)
        except ValueError as exc:
            raise BadRequestError(str(exc))
        if not target.exists():
            raise NotFoundError(f"M-code not found: {name}")
        text = target.read_text(encoding="utf-8")
        return MacroContentResponse(
            name=name,
            kind=MacroKind.MCODE,
            content=text,
            size_bytes=target.stat().st_size,
        )

    try:
        text = _macro_storage.read(name, kind=kind)
    except InvalidMacroNameError as exc:
        raise NotFoundError(str(exc))
    except InvalidMacroKindError as exc:
        raise BadRequestError(str(exc))
    except MacroNotFoundError as exc:
        raise NotFoundError(str(exc))
    return MacroContentResponse(
        name=name,
        kind=kind,
        content=text,
        size_bytes=_storage_size(name, kind),
    )


@router.put(
    "/{name}/content",
    summary="Write macro content (universal-editor envelope)",
    description=(
        "Persist the supplied payload and return the same envelope "
        "shape as the read endpoint. Empty payloads are normalised to "
        "``\"\\n\"`` so FastAPI's ``text/plain`` body validation does "
        "not reject brand-new files with ``422``."
    ),
    operation_id="writeMacroContent",
    response_model=MacroContentResponse,
    responses={
        400: {"description": "Invalid name or kind."},
    },
)
def write_macro_content(
    payload: MacroContentPayload,
    name: str = Path(..., description="Macro name without any extension."),
    kind: str = Query(
        MacroKind.MACRO,
        description="One of ``macro`` / ``ngc`` / ``mcode``.",
    ),
) -> MacroContentResponse:
    """Write a macro via the universal-editor envelope shape."""
    _validate_kind(kind)
    # Empty payloads land as ``"\n"`` so brand-new files clear the
    # ``text/plain`` body validator and the operator does not see a
    # ``422`` for "Create new macro" → leave blank → save.
    safe_content = "\n" if payload.content == "" else payload.content

    if kind == MacroKind.MCODE:
        _validate_mcode_name(name)
        service = get_mcode_service()
        try:
            service.write_file(name, safe_content)
        except ValueError as exc:
            raise BadRequestError(str(exc))
        target = service.safe_join(name)
        size = target.stat().st_size if target.exists() else 0
        return MacroContentResponse(
            name=name,
            kind=MacroKind.MCODE,
            content=safe_content,
            size_bytes=size,
        )

    try:
        size = _macro_storage.write(name, safe_content, kind=kind)
    except InvalidMacroNameError as exc:
        raise BadRequestError(str(exc))
    except InvalidMacroKindError as exc:
        raise BadRequestError(str(exc))
    return MacroContentResponse(
        name=name,
        kind=kind,
        content=safe_content,
        size_bytes=size,
    )


__all__ = [
    "router",
    "MacroListItem",
    "MacroListResponse",
    "MacroWriteResponse",
    "MacroContentPayload",
    "MacroContentResponse",
    "VALID_KINDS",
    "EXTENSION",
]
