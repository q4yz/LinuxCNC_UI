from __future__ import annotations

import logging
from fastapi import APIRouter, Body, Path, Query, Response

from storage.MacroStorage import MacroKind
from services.MacroService import MacroListResponse, get_macros_service, MacroWriteResponse, MacroContentResponse, \
    MacroContentPayload

logger = logging.getLogger("backend.macros_service")

router = APIRouter(
    prefix="/api/v1/modules/macros",
    tags=["modules:macros"],
)


@router.get(
    "",
    response_model=MacroListResponse,
    summary="List macros",
    operation_id="listMacros",
)
def list_macros(
    kind: str = Query(MacroKind.MACRO, description="One of ``macro`` / ``ngc`` / ``mcode``."),
) -> MacroListResponse:
    return get_macros_service().list_macros(kind)


@router.get(
    "/{name}",
    summary="Read macro",
    operation_id="readMacro",
    response_class=Response,
    responses={
        200: {"description": "Raw macro payload.", "content": {"text/plain": {}}},
        404: {"description": "No macro with that name."},
        400: {"description": "Invalid name or kind."},
    },
)
def read_macro(
    name: str = Path(..., description="Macro name without any extension."),
    kind: str = Query(MacroKind.MACRO, description="One of ``macro`` / ``ngc`` / ``mcode``."),
) -> Response:
    content = get_macros_service().read_macro(name, kind)
    return Response(content=content, media_type="text/plain")


@router.put(
    "/{name}",
    response_model=MacroWriteResponse,
    summary="Create or overwrite a macro",
    operation_id="writeMacro",
)
def write_macro(
    name: str = Path(..., description="Macro name without any extension."),
    kind: str = Query(MacroKind.MACRO, description="One of ``macro`` / ``ngc`` / ``mcode``."),
    content: str = Body(..., media_type="text/plain", description="Raw macro payload (any text content)."),
) -> MacroWriteResponse:
    return get_macros_service().write_macro(name, kind, content)


@router.delete(
    "/{name}",
    status_code=204,
    summary="Delete a macro",
    operation_id="deleteMacro",
    responses={
        204: {"description": "Macro deleted."},
        404: {"description": "No macro with that name."},
        400: {"description": "Invalid name or kind."},
    },
)
def delete_macro(
    name: str = Path(..., description="Macro name without any extension."),
    kind: str = Query(MacroKind.MACRO, description="One of ``macro`` / ``ngc`` / ``mcode``."),
) -> Response:
    get_macros_service().delete_macro(name, kind)
    return Response(status_code=204)


# ---------------------------------------------------------------------- #
# Universal-editor content endpoints                                       #
# ---------------------------------------------------------------------- #

@router.get(
    "/{name}/content",
    summary="Read macro content (universal-editor envelope)",
    operation_id="readMacroContent",
    response_model=MacroContentResponse,
    responses={
        404: {"description": "No macro with that name."},
        400: {"description": "Invalid name or kind."},
    },
)
def read_macro_content(
    name: str = Path(..., description="Macro name without any extension."),
    kind: str = Query(MacroKind.MACRO, description="One of ``macro`` / ``ngc`` / ``mcode``."),
) -> MacroContentResponse:
    return get_macros_service().read_macro_content(name, kind)


@router.put(
    "/{name}/content",
    summary="Write macro content (universal-editor envelope)",
    operation_id="writeMacroContent",
    response_model=MacroContentResponse,
    responses={
        400: {"description": "Invalid name or kind."},
    },
)
def write_macro_content(
    payload: MacroContentPayload,
    name: str = Path(..., description="Macro name without any extension."),
    kind: str = Query(MacroKind.MACRO, description="One of ``macro`` / ``ngc`` / ``mcode``."),
) -> MacroContentResponse:
    return get_macros_service().write_macro_content(name, kind, payload.content)


# NOTE: ``POST /{name}/start`` (operation_id ``startMacro``) lives in the
# machine backend (``backend/machine/routers/macro_start.py``) because it
# dispatches MDI commands over the NML channel. nginx routes
# ``/api/v1/modules/macros/<name>/start`` to the machine backend and every
# other macros path here — the frontend contract is unchanged.
