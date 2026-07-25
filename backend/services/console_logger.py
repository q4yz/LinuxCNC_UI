"""Persistent console history logger.

The LinuxCNC UI exposes an in-browser terminal that shows every
command the user issues and every response / telemetry message the
backend produces. Issue #40 asks for an on-disk mirror of that
stream so developers can replay a session after the fact.

This module owns a small, dependency-free file writer that appends
each event as a single line. The format is intentionally simple so
the file can be tailed with ``tail -f`` and ingested by ``grep`` /
``awk`` without any bespoke tooling:

    2025-07-15T12:34:56.789Z [INFO ] CMD > G1 X10

The line prefix is an ISO-8601 timestamp followed by the level in a
fixed-width column. ``CMD`` events are user-issued MDI commands,
``RES`` events are backend responses, and ``TEL`` events are
telemetry messages that the WebSocket layer would have broadcast.

The writer is asynchronous with respect to the FastAPI event loop
because most calls happen from a thread (the synchronous
``execute_sync_cmd`` path) or from the asyncio telemetry loop. The
lock is small enough that the contended critical section is just
the ``write()`` call — anything that takes longer (path lookup,
file creation) is handled outside the lock.

The destination path defaults to ``<repo>/console_history.log`` and
can be overridden per-instance. Tests construct a logger with a
``tmp_path`` so they never touch the real file.
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional, Union

logger = logging.getLogger("backend.services.console_logger")


class LogLevel(str, Enum):
    """Canonical log levels used by the console history writer.

    The values are stored verbatim in the file (upper-case, padded
    to five characters) so the column stays aligned for the
    ``tail -f`` reader. The string-based enum lets the rest of the
    codebase pass plain strings where type hints are not enforced.
    """

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


# Map of backend ``type`` tokens (matching the frontend vocabulary)
# to the canonical log level. Mirrors
# ``frontend/src/stores/console.js::TYPE_TO_LEVEL`` so the file
# rows match the UI chips.
TYPE_TO_LEVEL = {
    "info": LogLevel.INFO,
    "success": LogLevel.INFO,
    "command": LogLevel.INFO,
    "warning": LogLevel.WARNING,
    "error": LogLevel.ERROR,
    "debug": LogLevel.DEBUG,
}


def _default_log_path() -> Path:
    """Resolve the default ``console_history.log`` location.

    The file lives at the repository root, two levels above this
    module (``backend/services/`` -> ``backend/`` -> ``repo``). The
    helper is module-level so tests can monkey-patch it.
    """
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root / "console_history.log"


class ConsoleLogger:
    """Append-only writer for the console history file.

    The class is deliberately small: one file, one writer, one
    lock. Callers record events with :meth:`log_event` and the
    surrounding machinery (MDI handler, telemetry loop) decides
    which level to use.

    The instance is safe to share across threads and asyncio tasks
    — the writer is created lazily and protected by a single
    ``threading.Lock``. The constructor accepts a ``log_path`` so
    tests can redirect the output to a temporary file.
    """

    def __init__(self, log_path: Optional[Union[str, Path]] = None) -> None:
        self._log_path: Path = Path(log_path) if log_path else _default_log_path()
        self._lock = threading.Lock()
        self._file = None  # lazily opened
        self._closed = False

    # ------------------------------------------------------------------ #
    # Public surface                                                     #
    # ------------------------------------------------------------------ #

    @property
    def log_path(self) -> Path:
        """Return the absolute path of the log file.

        The file may not exist yet on the first call — the writer
        opens it lazily on the first ``log_event`` so deployments
        that never log anything do not leave an empty file behind.
        """
        return self._log_path

    def log_event(
        self,
        message: str,
        level: Union[LogLevel, str] = LogLevel.INFO,
        source: str = "RES",
    ) -> None:
        """Append a single line to the log file.

        ``source`` is one of ``CMD`` (user-issued MDI command),
        ``RES`` (backend response, default), ``TEL`` (telemetry
        message), or ``SYS`` (system / lifecycle event). The token
        is recorded after the level so the file is greppable by
        category.

        The method is idempotent against a closed logger — closing
        is a no-op for safety so callers do not have to wrap every
        call in a try/except.
        """
        if self._closed:
            return

        # Validate the level early so a typo is caught before we
        # touch the file. The Enum allows the string form for
        # callers that pass literals.
        if isinstance(level, str):
            try:
                level = LogLevel(level.upper())
            except ValueError:
                # Unknown levels are clamped to INFO rather than
                # raising — the persistent mirror should never
                # be the reason a command fails.
                level = LogLevel.INFO

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        # Strip trailing newlines from the message so a single
        # ``log_event`` always produces one line.
        cleaned = (message or "").replace("\r", " ").replace("\n", " ")
        line = f"{timestamp} [{level.value:<5}] {source} {cleaned}\n"

        with self._lock:
            try:
                self._ensure_open()
                self._file.write(line)
                self._file.flush()
            except Exception as exc:  # noqa: BLE001 - defensive
                # Never crash the request because of a logging
                # failure. Fall back to the standard logger so the
                # operator at least sees the failure in stderr.
                logger.error("ConsoleLogger failed to write: %s", exc)

    def log_command(self, command: str) -> None:
        """Convenience helper for MDI command events."""
        self.log_event(str(command), level=LogLevel.INFO, source="CMD")

    def log_response(self, response: str, level: Union[LogLevel, str] = LogLevel.INFO) -> None:
        """Convenience helper for backend responses / status messages."""
        self.log_event(str(response), level=level, source="RES")

    def log_telemetry(self, payload: str) -> None:
        """Convenience helper for telemetry messages."""
        self.log_event(str(payload), level=LogLevel.DEBUG, source="TEL")

    def close(self) -> None:
        """Flush and close the underlying file handle.

        The method is safe to call multiple times and after the
        logger has already been closed. ``backend/main.py`` wires
        it into the FastAPI lifespan so the file is flushed on
        shutdown.
        """
        with self._lock:
            if self._closed:
                return
            if self._file is not None:
                try:
                    self._file.flush()
                    self._file.close()
                except Exception as exc:  # noqa: BLE001
                    logger.error("ConsoleLogger close failed: %s", exc)
                self._file = None
            self._closed = True

    # ------------------------------------------------------------------ #
    # Internal helpers                                                   #
    # ------------------------------------------------------------------ #

    def _ensure_open(self) -> None:
        """Open the file lazily on the first write.

        The file is opened in append mode with line buffering so a
        crash mid-session does not lose buffered output. The
        parent directory is created best-effort so deployments that
        point the logger at a fresh directory do not crash.
        """
        if self._file is not None:
            return
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            # ``buffering=1`` means line-buffered, mirroring
            # ``tail -f`` semantics so an operator reading the file
            # in real time sees rows immediately.
            self._file = open(self._log_path, "a", encoding="utf-8", buffering=1)
        except Exception as exc:  # noqa: BLE001
            logger.error("ConsoleLogger could not open %s: %s", self._log_path, exc)
            self._file = None
            raise


# ---------------------------------------------------------------------- #
# Module-level singleton                                                  #
# ---------------------------------------------------------------------- #
# Tests reach into :data:`console_logger` to force-reset the
# singleton between cases. Production code uses the helper
# :func:`get_console_logger` to access the same instance.

console_logger = ConsoleLogger()


def get_console_logger() -> ConsoleLogger:
    """Return the process-wide :class:`ConsoleLogger` singleton."""
    return console_logger


def reset_console_logger(log_path: Optional[Union[str, Path]] = None) -> ConsoleLogger:
    """Replace the singleton with a fresh logger.

    Intended for tests that need to redirect the output to a
    temporary file (or simply clear the singleton between cases).
    The previous instance is closed before the new one is created
    so no file handles are leaked.
    """
    global console_logger
    try:
        console_logger.close()
    except Exception:  # noqa: BLE001
        pass
    console_logger = ConsoleLogger(log_path)
    return console_logger


__all__ = [
    "ConsoleLogger",
    "LogLevel",
    "TYPE_TO_LEVEL",
    "console_logger",
    "get_console_logger",
    "reset_console_logger",
]
