"""Macro execution — machine-backend half of the macros domain.

``POST /api/v1/modules/macros/{name}/start`` dispatches MDI commands
over the NML channel, so it must live in the machine backend next to
the other hardware-coupled services. The file-CRUD half of the macros
domain (list/read/write/delete/content) lives in the system service.

Extracted verbatim from the former monolithic ``MacrosService.start_macro``
during the two-service split.
"""
import logging
import math
import threading
import time
from typing import Any, List, Optional, Sequence

from exceptions import BadRequestError, ConflictError, NotFoundError

from domain_file_services import get_macro_service, get_mcode_service
from hardware import dispatch_mdi, get_stat_channel, linuxcnc
from hardware.Connection import MachineMode, MachineState
from services.ConsoleLogger import get_console_logger, LogLevel
from services.macro.macro_parser import MacroBlock, split_static_block, MacroParseError, parse_macro

logger = logging.getLogger("backend.macro_execution_service")


class MacroKind:
    MACRO = "macro"
    NGC = "ngc"
    MCODE = "mcode"


VALID_KINDS = (MacroKind.MACRO, MacroKind.NGC, MacroKind.MCODE)

_MCODE_RE_LOGIC = "M-codes cannot be started from the machine backend"

_INTERP_IDLE = getattr(linuxcnc, "INTERP_IDLE", 1)
_IDLE_POLL_S = 0.05


class MacroExecutionService:
    """Reads a macro from disk and executes it via the MDI channel.

    Validation, parsing and the machine pre-flight run inside the
    request so their errors still reach the caller; the line-by-line
    dispatch then runs on a background worker thread so the HTTP
    request returns immediately instead of staying open for the whole
    macro. Only one macro runs at a time.
    """

    def __init__(self) -> None:
        self._worker: Optional[threading.Thread] = None
        self._worker_lock = threading.Lock()

    def is_running(self) -> bool:
        worker = self._worker
        return worker is not None and worker.is_alive()

    def join(self, timeout: Optional[float] = None) -> None:
        """Wait for the running macro (if any) to finish."""
        worker = self._worker
        if worker is not None:
            worker.join(timeout)

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

    @staticmethod
    def _format_args(args: Sequence[float]) -> str:
        """``[1.5, 10]`` -> ``" [1.5] [10]"`` — the positional ``#1``,
        ``#2``, ... of an ``o<name> call``.

        Fixed-point only: G-code has no exponent notation, so ``1e-05``
        would be a parse error on the controller.
        """
        parts = []
        for value in args:
            if not math.isfinite(value):
                raise BadRequestError(f"Macro argument must be a finite number, got {value!r}")
            text = f"{value:.6f}".rstrip("0").rstrip(".")
            parts.append(f" [{'0' if text in ('', '-0') else text}]")
        return "".join(parts)

    def start_macro(self, name: str, kind: str, args: Optional[Sequence[float]] = None) -> None:
        """Verify the macro exists and start executing it via the MDI channel.

        ``args`` become the positional parameters (``#1``, ``#2``, ...)
        of an ``.ngc`` subroutine call. Returns as soon as the macro is
        running; progress and failures are reported through the
        console log.
        """
        self._validate_kind(kind)
        args = list(args or [])

        if kind not in (MacroKind.MACRO, MacroKind.NGC):
            raise BadRequestError(
                f"Running {kind!r} files from the UI is not supported — "
                "wrap the call in a .macro file instead."
            )

        if args and kind != MacroKind.NGC:
            raise BadRequestError(
                "Macro arguments are only supported for .ngc subroutines."
            )
        call_args = self._format_args(args)

        body = self._read_macro_body(name, kind)

        stat = get_stat_channel()
        if stat is None:
            raise BadRequestError("Cannot execute macro: LinuxCNC is not running.")

        stat.poll()

        if stat.estop:
            raise BadRequestError("Cannot execute macro while machine is in E-STOP.")

        if stat.task_state != MachineState.ON.value:
            raise BadRequestError(f"Machine must be ON to execute a macro. Current state: {stat.task_state}")

        if self.is_running():
            raise ConflictError("Another macro is still running.")

        if kind == MacroKind.NGC:
            # One subroutine call, run on the same worker as a .macro so
            # it counts as "running" until the interpreter is idle again
            # — a double-clicked probe cycle gets a 409, not a second
            # queued probe move.
            blocks = [MacroBlock(type="static", content=f"o<{name}> call{call_args}")]
        else:
            try:
                blocks = parse_macro(body)
            except MacroParseError as exc:
                get_console_logger().log_event(
                    f"Macro '{name}' failed to parse: {exc}",
                    level=LogLevel.ERROR,
                    source="CMD",
                )
                raise BadRequestError(str(exc))

        with self._worker_lock:
            if self.is_running():
                raise ConflictError("Another macro is still running.")
            self._worker = threading.Thread(
                target=self._run_worker,
                args=(name, blocks),
                name=f"macro-{name}",
                daemon=True,
            )
            self._worker.start()

    def _run_worker(self, name: str, blocks: List[MacroBlock]) -> None:
        """Thread entry point — never lets an exception escape silently."""
        try:
            self._run_blocks(name, blocks)
        except Exception as exc:  # noqa: BLE001 - report, don't kill silently
            logger.exception("Macro '%s' crashed: %s", name, exc)
            get_console_logger().log_event(
                f"Macro '{name}' aborted: {exc}",
                level=LogLevel.ERROR,
                source="CMD",
            )

    def _run_blocks(self, name: str, blocks: List[MacroBlock]) -> None:
        """Dispatch every static line in order, one finished move at a time."""
        console = get_console_logger()

        # ``stat`` is per-thread (channel_stat.py) — this worker needs its own.
        stat = get_stat_channel()
        if stat is None:
            console.log_event(
                f"Macro '{name}' aborted: LinuxCNC is not running.",
                level=LogLevel.ERROR,
                source="CMD",
            )
            return

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
                    serial = dispatch_mdi(line)
                    static_dispatched += 1
                except Exception as exc:  # noqa: BLE001 - keep the loop going
                    logger.warning("Macro '%s' line '%s' failed: %s", name, line, exc)
                    continue

                reason = self._wait_until_idle(stat, serial)
                if reason is not None:
                    console.log_event(
                        f"Macro '{name}' aborted: {reason}",
                        level=LogLevel.ERROR,
                        source="CMD",
                    )
                    return

        console.log_event(
            f"Macro '{name}' dispatched {static_dispatched} MDI command(s); skipped {python_skipped} python block(s).",
            level=LogLevel.INFO,
            source="CMD",
        )

    @staticmethod
    def _wait_until_idle(stat: Any, serial: Optional[int]) -> Optional[str]:
        """Block this worker thread until the dispatched line has finished.

        Polls ``stat`` instead of holding the command lock through
        ``wait_complete`` — jogs, stops and other commands stay
        responsive while a macro move is running. Returns ``None`` once
        the interpreter is idle again, or the reason the macro has to
        stop (E-stop, machine off, someone left MDI mode).
        """
        while True:
            stat.poll()
            if stat.estop:
                return "machine entered E-Stop during dispatch."
            if stat.task_state != MachineState.ON.value:
                return "machine was turned off."
            if getattr(stat, "task_mode", MachineMode.MDI) != MachineMode.MDI:
                return "machine left MDI mode."

            received = serial is None or getattr(stat, "echo_serial_number", serial) >= serial
            if received and getattr(stat, "interp_state", _INTERP_IDLE) == _INTERP_IDLE:
                return None
            time.sleep(_IDLE_POLL_S)


# Singleton provider
_SERVICE_INSTANCE: MacroExecutionService | None = None


def get_macro_execution_service() -> MacroExecutionService:
    global _SERVICE_INSTANCE
    if _SERVICE_INSTANCE is None:
        _SERVICE_INSTANCE = MacroExecutionService()
    return _SERVICE_INSTANCE
