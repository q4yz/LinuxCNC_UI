"""Macro file CRUD — system-service half of the macros domain.

The two-service split divided the former monolithic ``MacrosService``
along its only hardware seam: list/read/write/delete/content stay in
the system service (pure filesystem, always available), while
``POST /{name}/start`` — which dispatches MDI commands over the NML
channel — lives in the machine backend's
:class:`services.MacroExecutionService`.
"""
import logging
import re
from typing import List

from pydantic import BaseModel, Field

from exceptions import BadRequestError, NotFoundError


from domain_file_services import get_macro_service, get_mcode_service

logger = logging.getLogger("backend.macros_service")

# --- (Pydantic Models remain exactly the same as before) ---
class MacroKind:
    MACRO = "macro"
    NGC = "ngc"
    MCODE = "mcode"

VALID_KINDS = (MacroKind.MACRO, MacroKind.NGC, MacroKind.MCODE)


class MacroListItem(BaseModel):
    name: str = Field(..., description="File name without extension.")
    kind: str = Field(..., description="One of macro / ngc / mcode.")
    size_bytes: int = Field(..., description="On-disk byte size.")


class MacroListResponse(BaseModel):
    macros: List[MacroListItem] = Field(
        default_factory=list,
        description="Macro entries of the requested kind, sorted by name.",
    )


class MacroWriteResponse(BaseModel):
    name: str = Field(..., description="File name (no extension).")
    kind: str = Field(..., description="One of macro / ngc / mcode.")
    size: int = Field(..., description="Size of the persisted payload in bytes.")


class MacroContentPayload(BaseModel):
    content: str = Field(..., description="Raw macro payload (UTF-8 text).")


class MacroContentResponse(BaseModel):
    name: str = Field(..., description="File name (no extension).")
    kind: str = Field(..., description="One of macro / ngc / mcode.")
    content: str = Field(..., description="Raw text content of the file.")
    size_bytes: int = Field(..., description="On-disk byte size.")

class MacrosService:
    """Service handling macro read/write operations and domain validation."""

    def __init__(self):
        # We now grab the lazily-instantiated services via the factories
        self._macro_service = get_macro_service()
        self._mcode_service = get_mcode_service()
        self._MCODE_RE = re.compile(r"^M1\d{2}$")

    def _validate_kind(self, kind: str) -> str:
        if kind not in VALID_KINDS:
            raise BadRequestError(f"Unknown macro kind: {kind!r}; expected one of {VALID_KINDS}")
        return kind

    def _validate_mcode_name(self, name: str) -> str:
        if not self._MCODE_RE.match(name):
            raise BadRequestError(f"Invalid M-code name: {name!r} (must match ^M1\\d{{2}}$)")
        return name

    def _get_service(self, kind: str):
        """Route the file operation to the correct underlying domain FileService."""
        if kind == MacroKind.MCODE:
            return self._mcode_service
        return self._macro_service

    def _resolve_filename(self, name: str, kind: str) -> str:
        """Construct the physical filename based on the logical name and kind."""
        if kind == MacroKind.MCODE:
            return self._validate_mcode_name(name)
        return f"{name}.{kind}"

    def _storage_size(self, name: str, kind: str) -> int:
        service = self._get_service(kind)
        filename = self._resolve_filename(name, kind)
        try:
            target = service.safe_join(filename)
            return target.stat().st_size if target.exists() else 0
        except ValueError:
            return 0

    def list_macros(self, kind: str) -> MacroListResponse:
        self._validate_kind(kind)
        service = self._get_service(kind)

        items = []
        for entry in service.list_files():
            if entry.kind != "file":
                continue

            if kind == MacroKind.MCODE:
                if self._MCODE_RE.match(entry.name):
                    items.append(MacroListItem(name=entry.name, kind=kind, size_bytes=entry.size_bytes))
            else:
                ext = f".{kind}"
                if entry.name.endswith(ext):
                    # Strip the extension for the logical API response
                    base_name = entry.name[:-len(ext)]
                    items.append(MacroListItem(name=base_name, kind=kind, size_bytes=entry.size_bytes))

        items.sort(key=lambda item: item.name)
        return MacroListResponse(macros=items)

    def read_macro(self, name: str, kind: str) -> str:
        self._validate_kind(kind)
        service = self._get_service(kind)
        filename = self._resolve_filename(name, kind)

        try:
            target = service.safe_join(filename)
            if not target.exists():
                raise NotFoundError(f"{kind} not found: {name}")
            return target.read_text(encoding="utf-8")
        except ValueError as exc:
            raise BadRequestError(str(exc))

    def write_macro(self, name: str, kind: str, content: str) -> MacroWriteResponse:
        self._validate_kind(kind)
        service = self._get_service(kind)
        filename = self._resolve_filename(name, kind)

        try:
            service.write_file(filename, content)
            target = service.safe_join(filename)
            size = target.stat().st_size if target.exists() else 0
            return MacroWriteResponse(name=name, kind=kind, size=size)
        except ValueError as exc:
            raise BadRequestError(str(exc))

    def delete_macro(self, name: str, kind: str) -> None:
        self._validate_kind(kind)
        service = self._get_service(kind)
        filename = self._resolve_filename(name, kind)

        try:
            target = service.safe_join(filename)
            if not target.exists():
                raise NotFoundError(f"{kind} not found: {name}")
            service.delete(filename)
        except ValueError as exc:
            raise BadRequestError(str(exc))

    def read_macro_content(self, name: str, kind: str) -> MacroContentResponse:
        content = self.read_macro(name, kind)
        return MacroContentResponse(
            name=name,
            kind=kind,
            content=content,
            size_bytes=self._storage_size(name, kind),
        )

    def write_macro_content(self, name: str, kind: str, content: str) -> MacroContentResponse:
        # Empty payloads land as "\n" to bypass text/plain body validator quirks
        safe_content = "\n" if content == "" else content
        write_result = self.write_macro(name, kind, safe_content)

        return MacroContentResponse(
            name=write_result.name,
            kind=write_result.kind,
            content=safe_content,
            size_bytes=write_result.size,
        )

# Singleton provider
_SERVICE_INSTANCE = None

def get_macros_service() -> MacrosService:
    global _SERVICE_INSTANCE
    if _SERVICE_INSTANCE is None:
        _SERVICE_INSTANCE = MacrosService()
    return _SERVICE_INSTANCE