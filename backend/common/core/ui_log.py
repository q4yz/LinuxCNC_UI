"""Application logging for the UI backends.

Each backend logs to stderr (journal / LinuxCNC console, as before)
*and* to its own file under ``logs/`` (``domain_file_services.paths``),
so the operator can read the UI's log apart from LinuxCNC's — see
``GET /api/v1/system/machine/log/ui``.

The machine backend runs inside LinuxCNC (``loadusr`` in ``custom.hal``),
so its stdout/stderr end up in LinuxCNC's own log and cannot be kept
out of it. :func:`tag_std_streams` starts each of those lines with
``UI_PREFIX``; the LinuxCNC log tags every other line with
``LINUXCNC_PREFIX`` when read, so it can be sorted / filtered by source.
"""
from __future__ import annotations

import logging
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Optional, TextIO

#: Keeps the log small on an SD card: 1 MB plus two rotated files.
_MAX_BYTES = 1024 * 1024
_BACKUP_COUNT = 2
_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

UI_PREFIX = "UI: "
LINUXCNC_PREFIX = "LinuxCNC: "
_LINE = re.compile(r"[^\n]*\n|[^\n]+")


class PrefixedStream:
    """Text stream wrapper that starts every line with ``prefix``.

    Writes may end mid-line (``print`` writes the text, then ``"\n"``),
    so the prefix goes in front of whatever follows a newline. Anything
    else (``isatty``, ``fileno``, ...) is the wrapped stream's.
    """

    def __init__(self, stream: TextIO, prefix: str) -> None:
        self._stream = stream
        self._prefix = prefix
        self._at_line_start = True

    def write(self, text: str) -> int:
        out = []
        for part in _LINE.findall(text):
            if self._at_line_start:
                out.append(self._prefix)
            out.append(part)
            self._at_line_start = part.endswith("\n")
        self._stream.write("".join(out))
        return len(text)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)


def tag_std_streams(prefix: str = UI_PREFIX) -> None:
    """Prefix every line this process writes to stdout / stderr (logging,
    uvicorn, ``print``, tracebacks). Call it before :func:`setup_ui_logging`
    — a ``StreamHandler`` keeps the stream it was created with."""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        if stream is not None and not isinstance(stream, PrefixedStream):
            setattr(sys, name, PrefixedStream(stream, prefix))


def setup_ui_logging(log_file: Optional[Path], level: int = logging.INFO) -> None:
    """Log to stderr and ``log_file`` (stderr only when ``None``).

    The file handler also goes on ``uvicorn`` (startup and request
    errors) when uvicorn's logging config stops it propagating to the
    root logger. A log file
    that cannot be opened only costs the file — the service still runs.
    """
    logging.basicConfig(level=level)
    if log_file is None:
        return
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            # delay: the file appears with its first line, not on import.
            log_file, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8", delay=True
        )
    except OSError as exc:
        logging.getLogger(__name__).warning("UI log file %s unavailable: %s", log_file, exc)
        return
    handler.setFormatter(logging.Formatter(_FORMAT))
    targets = [logging.getLogger("")]
    if not logging.getLogger("uvicorn").propagate:  # uvicorn's own config cuts it off from root
        targets.append(logging.getLogger("uvicorn"))
    added = False
    for logger in targets:
        # Idempotent: a re-import (--reload) must not double every line.
        if not any(getattr(h, "baseFilename", None) == handler.baseFilename for h in logger.handlers):
            logger.addHandler(handler)
            added = True
    if not added:
        handler.close()


__all__ = ["LINUXCNC_PREFIX", "PrefixedStream", "UI_PREFIX", "setup_ui_logging", "tag_std_streams"]
