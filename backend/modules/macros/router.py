"""HTTP API for custom macro files."""

from fastapi import APIRouter, HTTPException, Path
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from .service import MacroFileService, MacroNotFoundError


class MacroPayload(BaseModel):
    content: str


#: Path segment regex for the ``/{name}`` routes.
#:
#: Matches any non-empty single path segment (no embedded ``/``).
#: The macros router is mounted at ``/api/v1/modules/macros`` and
#: the registry mounts a canonical settings router under the
#: ``/settings`` sub-prefix of the same URL. The registry mounts
#: the settings router **first** (see
#: :meth:`core.module_registry.ModuleRegistry._mount`) so Starlette's
#: first-match-wins routing always resolves ``/settings`` and
#: ``/settings/{key}`` to the canonical settings handlers, never
#: to the macros router's ``/{name}`` catch-all. This keeps the
#: pattern simple — any single-segment name is accepted at the
#: router boundary; service-layer validation rejects names that
#: carry a non-``.macro`` suffix or empty stems.
NAME_PATH_PATTERN = r"[^/]+"


def create_router(service: MacroFileService) -> APIRouter:
    router = APIRouter()

    @router.get("/", summary="List macros", description="List available macro names.")
    def list_macros() -> list[str]:
        return service.list_macros()

    @router.get(
        "/{name}",
        summary="Read a macro",
        description="Read raw macro contents.",
        response_class=PlainTextResponse,
    )
    def read_macro(name: str = Path(..., pattern=NAME_PATH_PATTERN)) -> str:
        try:
            return service.read_macro(name)
        except MacroNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.put("/{name}", summary="Write a macro", description="Create or overwrite a macro.")
    def write_macro(
        payload: MacroPayload,
        name: str = Path(..., pattern=NAME_PATH_PATTERN),
    ) -> dict[str, str]:
        try:
            service.write_macro(name, payload.content)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"name": name.removesuffix(".macro")}

    @router.delete("/{name}", summary="Delete a macro", description="Delete a macro file.")
    def delete_macro(name: str = Path(..., pattern=NAME_PATH_PATTERN)) -> dict[str, str]:
        try:
            service.delete_macro(name)
        except MacroNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"name": name.removesuffix(".macro")}

    return router


__all__ = ["MacroPayload", "create_router"]