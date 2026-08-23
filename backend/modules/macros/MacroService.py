import logging
import re
from typing import List

from pydantic import BaseModel, Field

from exceptions import BadRequestError, NotFoundError
from hardware import get_machine_stat, execute_gcode
from hardware.Connection import MachineState, connection
from services import get_mcode_service

from backend.modules.macros.storage import (
    InvalidMacroKindError,
    InvalidMacroNameError,
    MacroKind,
    MacroNotFoundError,
    MacroStorage,
    default_storage_root,
)

logger = logging.getLogger("backend.modules.macros.service")

# ---------------------------------------------------------------------- #
# Pydantic models                                                         #
# ---------------------------------------------------------------------- #

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


# ---------------------------------------------------------------------- #
# Service logic                                                           #
# ---------------------------------------------------------------------- #

class MacrosService:
    """Service handling macro read/write operations and domain validation."""

    def __init__(self):
        self._macro_storage = MacroStorage(default_storage_root())
        self._MCODE_RE = re.compile(r"^M1\d{2}$")

    def _validate_kind(self, kind: str) -> str:
        if kind not in VALID_KINDS:
            raise BadRequestError(f"unknown macro kind: {kind!r}; expected one of {VALID_KINDS}")
        return kind

    def _validate_mcode_name(self, name: str) -> str:
        if not self._MCODE_RE.match(name):
            raise BadRequestError(f"invalid M-code name: {name!r} (must match ^M1\\d{{2}}$)")
        return name

    def _storage_size(self, name: str, kind: str) -> int:
        if kind == MacroKind.MCODE:
            service = get_mcode_service()
            for existing in service.list_files():
                if existing.name == name:
                    return existing.size_bytes
            return 0

        try:
            return self._macro_storage.size(name, kind=kind)
        except (InvalidMacroNameError, InvalidMacroKindError):
            return 0

    def list_macros(self, kind: str) -> MacroListResponse:
        self._validate_kind(kind)

        if kind == MacroKind.MCODE:
            service = get_mcode_service()
            entries = service.list_files()
            items = [
                MacroListItem(name=entry.name, kind=MacroKind.MCODE, size_bytes=entry.size_bytes)
                for entry in entries if entry.kind == "file"
            ]
        else:
            names = self._macro_storage.list(kind=kind)
            items = [
                MacroListItem(name=name, kind=kind, size_bytes=self._storage_size(name, kind))
                for name in names
            ]

        items.sort(key=lambda item: item.name)
        return MacroListResponse(macros=items)

    def read_macro(self, name: str, kind: str) -> str:
        self._validate_kind(kind)

        if kind == MacroKind.MCODE:
            self._validate_mcode_name(name)
            service = get_mcode_service()
            try:
                target = service.safe_join(name)
            except ValueError as exc:
                raise BadRequestError(str(exc))
            if not target.exists():
                raise NotFoundError(f"M-code not found: {name}")
            return target.read_text(encoding="utf-8")

        try:
            return self._macro_storage.read(name, kind=kind)
        except InvalidMacroNameError as exc:
            raise NotFoundError(str(exc))
        except InvalidMacroKindError as exc:
            raise BadRequestError(str(exc))
        except MacroNotFoundError as exc:
            raise NotFoundError(str(exc))

    def write_macro(self, name: str, kind: str, content: str) -> MacroWriteResponse:
        self._validate_kind(kind)

        if kind == MacroKind.MCODE:
            self._validate_mcode_name(name)
            service = get_mcode_service()
            try:
                service.write_file(name, content)
            except ValueError as exc:
                raise BadRequestError(str(exc))

            target = service.safe_join(name)
            size = target.stat().st_size if target.exists() else 0
            return MacroWriteResponse(name=name, kind=MacroKind.MCODE, size=size)

        try:
            size = self._macro_storage.write(name, content, kind=kind)
        except (InvalidMacroNameError, InvalidMacroKindError) as exc:
            raise BadRequestError(str(exc))

        return MacroWriteResponse(name=name, kind=kind, size=size)

    def delete_macro(self, name: str, kind: str) -> None:
        self._validate_kind(kind)

        if kind == MacroKind.MCODE:
            self._validate_mcode_name(name)
            service = get_mcode_service()
            try:
                target = service.safe_join(name)
            except ValueError as exc:
                raise BadRequestError(str(exc))
            if not target.exists():
                raise NotFoundError(f"M-code not found: {name}")
            target.unlink()
            return

        try:
            self._macro_storage.delete(name, kind=kind)
        except (InvalidMacroNameError, MacroNotFoundError) as exc:
            raise NotFoundError(str(exc))
        except InvalidMacroKindError as exc:
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

    def start_macro(self, name: str, kind: str) -> None:
        """Verifies the macro exists and executes it via the MDI channel."""
        self._validate_kind(kind)

        # 1. Verify the macro actually exists before trying to run it
        if kind != MacroKind.NGC:
            raise NotImplementedError("only ngc execution is supported currently")

        try:
            self._macro_storage.read(name, kind=kind)
        except (InvalidMacroNameError, MacroNotFoundError) as exc:
            raise NotFoundError(str(exc))
        except InvalidMacroKindError as exc:
            raise BadRequestError(str(exc))

        stat = connection.get_machine_stat()
        if stat is None:
            raise BadRequestError("Cannot execute macro: LinuxCNC is not running.")

        stat.poll()

        if stat.estop:
            raise BadRequestError("Cannot execute macro while machine is in E-STOP.")
        if stat.task_state != MachineState.ESTOP:
            raise BadRequestError("Machine must be ON to execute a macro.")

        gcode = name if kind == MacroKind.MCODE else f"o<{name}> call"

        connection.execute_gcode(gcode)


# Singleton provider
_SERVICE_INSTANCE = None


def get_macros_service() -> MacrosService:
    global _SERVICE_INSTANCE
    if _SERVICE_INSTANCE is None:
        _SERVICE_INSTANCE = MacrosService()
    return _SERVICE_INSTANCE