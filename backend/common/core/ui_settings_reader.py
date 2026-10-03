"""Read one UI setting by key from any process — uncached.

The system service is the only writer of ``data/settings.json``. Other
processes (the machine backend's camera supervisor) read the one key
they need through :func:`read_ui_setting`, which parses the file on
every call: a value the operator just saved is picked up immediately,
with no restart and no cache to go stale. The writer replaces the file
atomically, so a read never sees a partial document.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from domain_file_services.paths import UI_SETTINGS_FILE

logger = logging.getLogger(__name__)


def read_ui_setting(key: str, default: Any = None, path: Optional[Path] = None) -> Any:
    """Return the stored value for ``key``, or ``default`` when unset/unreadable."""
    file = Path(path) if path is not None else UI_SETTINGS_FILE
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except (OSError, ValueError) as exc:
        logger.warning("UI settings: cannot read %s (%s) — using default for %s", file, exc, key)
        return default
    if not isinstance(data, dict):
        return default
    return data.get(key, default)


__all__ = ["read_ui_setting"]
