import logging
import re
from typing import List

from pydantic import BaseModel, Field

from exceptions import BadRequestError, NotFoundError
from hardware import get_machine_stat, execute_gcode
from hardware.Connection import MachineState, connection
from services import get_mcode_service
from services.ConsoleLogger import LogLevel, get_console_logger
from services.macro_parser import (
    MacroParseError,
    parse_macro,
    split_static_block,
)

from storage.MacroStorage import (
    InvalidMacroKindError,
    InvalidMacroNameError,
    MacroKind,
    MacroNotFoundError,
    MacroStorage,
    default_storage_root,
)

logger = logging.getLogger("backend.macros_service")

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
        """Verify the macro exists and execute it via the MDI channel.

        Dispatch paths by kind:

        * ``.macro`` — read the file, parse it into ``static`` /
          ``python`` blocks (see :mod:`services.macro_parser`),
          then dispatch each non-blank static line via
          :func:`hardware.execute_gcode`. ``python`` blocks are
          skipped with a single WARNING line in the console
        log so the operator sees them, mirroring the
          behaviour the frontend parser used to provide. A
          mid-run E-Stop aborts the dispatch between lines so a
          dead machine does not receive the rest of the file.

        * ``.ngc`` — issue a single ``o<{name}> call`` MDI command
          so the controller switches to MDI mode and runs the
          NGC subroutine. The check-the-state-then-call-MDI
          dance is identical to ``.macro``.

        ``.mcode`` is intentionally not routed here — an operator
        who needs a custom M-code wraps it in a ``.macro`` (the
        frontend editor surfaces this convention on the
        ``MacroButton`` kind picker).
        """
        self._validate_kind(kind)

        # 1. Verify the macro actually exists before trying to run it.
        #    Read paths differ per kind: ``.macro`` and ``.ngc`` go
        #    through :class:`MacroStorage`; ``.mcode`` is rejected up
        #    front (see the .mcode block above).
        if kind not in (MacroKind.MACRO, MacroKind.NGC):
            raise BadRequestError(
                f"Running {kind!r} files from the UI is not supported — "
                "wrap the call in a .macro file instead."
            )

        try:
            body = self._macro_storage.read(name, kind=kind)
        except (InvalidMacroNameError, MacroNotFoundError) as exc:
            raise NotFoundError(str(exc))
        except InvalidMacroKindError as exc:
            raise BadRequestError(str(exc))

        # 2. Pre-flight the safety state once for the whole call
        #    (every MDI dispatch will switch to MDI mode anyway, but
        #    a fail-fast 400 here is friendlier than a stream of
        #    503s from the per-line dispatch loop).
        stat = connection.get_machine_stat()
        if stat is None:
            raise BadRequestError("Cannot execute macro: LinuxCNC is not running.")

        stat.poll()

        if stat.estop:
            raise BadRequestError("Cannot execute macro while machine is in E-STOP.")
        if stat.task_state is MachineState.ON:
            raise BadRequestError(f"Machine must be ON to execute a macro.{stat.task_state} {MachineState.ON}")

        # 3. Dispatch by kind.
        if kind == MacroKind.NGC:
            execute_gcode(f"o<{name}> call")
            return

        # kind == MacroKind.MACRO below.
        console = get_console_logger()
        try:
            blocks = parse_macro(body)
        except MacroParseError as exc:
            console.log_event(
                f"Macro '{name}' failed to parse: {exc}",
                level=LogLevel.ERROR,
                source="CMD",
            )
            raise BadRequestError(str(exc))

        static_dispatched = 0
        python_skipped = 0
        console.log_event(
            f"Running macro '{name}' ({len(blocks)} block(s)).",
            level=LogLevel.INFO,
            source="CMD",
        )

        for index, block in enumerate(blocks):
            if block.type == "python":
                python_skipped += 1
                console.log_event(
                    f"Macro '{name}' block #{index + 1}: python block skipped — interpreter not implemented yet.",
                    level=LogLevel.WARNING,
                    source="CMD",
                )
                continue

            for line in split_static_block(block.content):
                # Mid-run safety re-check: an E-Stop issued during
                # dispatch must abort the remaining commands instead
                # of feeding them to a dead machine.
                stat.poll()
                if stat.estop:
                    console.log_event(
                        f"Macro '{name}' aborted: machine entered E-Stop during dispatch.",
                        level=LogLevel.ERROR,
                        source="CMD",
                    )
                    return
                try:
                    execute_gcode(line)
                    static_dispatched += 1
                except Exception as exc:  # noqa: BLE001 - keep the loop going
                    # ``execute_gcode`` already raises HTTPException-shaped
                    # errors; the loop continues so a single failed
                    # line does not invalidate the remaining commands.
                    logger.warning("Macro '%s' line '%s' failed: %s", name, line, exc)

        console.log_event(
            f"Macro '{name}' dispatched {static_dispatched} MDI command(s); skipped {python_skipped} python block(s).",
            level=LogLevel.INFO,
            source="CMD",
        )


# Singleton provider
_SERVICE_INSTANCE = None


def get_macros_service() -> MacrosService:
    global _SERVICE_INSTANCE
    if _SERVICE_INSTANCE is None:
        _SERVICE_INSTANCE = MacrosService()
    return _SERVICE_INSTANCE