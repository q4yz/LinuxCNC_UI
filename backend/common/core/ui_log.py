"""Application logging for the UI backends.

Each backend logs to stderr (journal / LinuxCNC console, as before)
*and* to its own file under ``logs/`` (``domain_file_services.paths``),
so the operator can read the UI's log apart from LinuxCNC's — see
``GET /api/v1/system/machine/log/ui``.
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

#: Keeps the log small on an SD card: 1 MB plus two rotated files.
_MAX_BYTES = 1024 * 1024
_BACKUP_COUNT = 2
_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


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


__all__ = ["setup_ui_logging"]
