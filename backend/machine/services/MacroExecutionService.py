"""Macro execution — machine-backend half of the macros domain.

``POST /api/v1/modules/macros/{name}/start`` dispatches MDI commands
over the NML channel, so it must live in the machine backend next to
the other hardware-coupled services. The file-CRUD half of the macros
domain (list/read/write/delete/content) lives in the system service.

Extracted verbatim from the former monolithic ``MacrosService.start_macro``
during the two-service split.
"""
import logging

from exceptions import BadRequestError, NotFoundError

from domain_file_services import get_macro_service, get_mcode_service
from hardware import execute_gcode, get_stat_channel
from hardware.Connection import MachineState
from services.ConsoleLogger import get_console_logger, LogLevel
from services.macro.macro_parser import split_static_block, MacroParseError, parse_macro

logger = logging.getLogger("backend.macro_execution_service")


class MacroKind:
    MACRO = "macro"
    NGC = "ngc"
    MCODE = "mcode"


VALID_KINDS = (MacroKind.MACRO, MacroKind.NGC, MacroKind.MCODE)

_MCODE_RE_LOGIC = "M-codes cannot be started from the machine backend"


class MacroExecutionService:
    """Reads a macro from disk and executes it via the MDI channel."""

    def _validate_kind(self, kind: str) -> str:
        if kind not in VALID_KINDS:
            raise BadRequestError(
                f"Unknown macro kind: {kind!r}; expected one of {VALID_KINDS}"
            )
        return kind

    def _read_macro_body(self, name: str, kind: str) -> str:
        """Read the macro payload with presence + path validation.

        Mirrors :meth:`MacrosService.read_macro` from the system
        service (the machine backend cannot import the other app's
        package, so the small read helper is duplicated here).
        """
        service = (
            get_mcode_service()
            if kind == MacroKind.MCODE
            else get_macro_service()
        )
        filename = name if kind == MacroKind.MCODE else f"{name}.{kind}"
        try:
            target = service.safe_join(filename)
            if not target.exists():
                raise NotFoundError(f"{kind} not found: {name}")
            return target.read_text(encoding="utf-8")
        except ValueError as exc:
            raise BadRequestError(str(exc))

    def start_macro(self, name: str, kind: str) -> None:
        """Verify the macro exists and execute it via the MDI channel."""
        self._validate_kind(kind)

        if kind not in (MacroKind.MACRO, MacroKind.NGC):
            raise BadRequestError(
                f"Running {kind!r} files from the UI is not supported — "
                "wrap the call in a .macro file instead."
            )

        body = self._read_macro_body(name, kind)

        stat = get_stat_channel()
        if stat is None:
            raise BadRequestError("Cannot execute macro: LinuxCNC is not running.")

        stat.poll()

        if stat.estop:
            raise BadRequestError("Cannot execute macro while machine is in E-STOP.")

        if stat.task_state != MachineState.ON.value:
            raise BadRequestError(f"Machine must be ON to execute a macro. Current state: {stat.task_state}")

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
                    logger.warning("Macro '%s' line '%s' failed: %s", name, line, exc)

        console.log_event(
            f"Macro '{name}' dispatched {static_dispatched} MDI command(s); skipped {python_skipped} python block(s).",
            level=LogLevel.INFO,
            source="CMD",
        )


# Singleton provider
_SERVICE_INSTANCE: MacroExecutionService | None = None


def get_macro_execution_service() -> MacroExecutionService:
    global _SERVICE_INSTANCE
    if _SERVICE_INSTANCE is None:
        _SERVICE_INSTANCE = MacroExecutionService()
    return _SERVICE_INSTANCE
