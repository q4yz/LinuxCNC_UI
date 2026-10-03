"""The single UI settings store: one JSON document, flat ``{key: value}``.

Owned by the system service (always running, also while the machine
backend is down). The frontend owns every setting's type, default and
validation (``frontend/src/settings``); this store only guarantees:

* keys are namespaced identifiers (``camera.ip_camera_url``) — never a
  path, so a key can't escape the data directory;
* values are JSON and bounded in size;
* writes are atomic (``atomic_write_json``), so other processes reading
  the file (``ui_settings_reader``) never see a partial document.

A key that was never written is simply *unset* — there are no backend
defaults.
"""
from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from core.atomic_json import atomic_write_json

logger = logging.getLogger(__name__)

#: ``<namespace>.<name>[.<more>]`` — lowercase, digits, underscores.
KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$")
#: Upper bound for one serialized value — settings are small; this only
#: stops a buggy client from bloating the shared document.
MAX_VALUE_BYTES = 64 * 1024


class InvalidSettingKeyError(ValueError):
    pass


class SettingValueTooLargeError(ValueError):
    pass


def validate_key(key: str) -> str:
    if not isinstance(key, str) or not KEY_PATTERN.match(key):
        raise InvalidSettingKeyError(
            f"Invalid setting key {key!r}: expected a namespaced id like 'camera.ip_camera_url'"
        )
    return key


class UiSettingsStore:
    """Read/write access to the UI settings document for one process."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._cache: Optional[Dict[str, Any]] = None
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def _load(self) -> Dict[str, Any]:
        """Parse the file; a missing or corrupt file reads as empty."""
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("UI settings: %s unreadable (%s) — treating as empty", self._path, exc)
            return {}
        if not isinstance(data, dict):
            logger.warning("UI settings: %s is not a JSON object — treating as empty", self._path)
            return {}
        return data

    def read_all(self) -> Dict[str, Any]:
        with self._lock:
            if self._cache is None:
                self._cache = self._load()
            return dict(self._cache)

    def has_key(self, key: str) -> bool:
        validate_key(key)
        return key in self.read_all()

    def read_key(self, key: str, default: Any = None) -> Any:
        validate_key(key)
        return self.read_all().get(key, default)

    def write_key(self, key: str, value: Any) -> Any:
        """Persist ``value`` under ``key``; returns the stored value."""
        validate_key(key)
        encoded = json.dumps(value)
        if len(encoded.encode("utf-8")) > MAX_VALUE_BYTES:
            raise SettingValueTooLargeError(
                f"Setting {key!r} value exceeds {MAX_VALUE_BYTES} bytes"
            )
        with self._lock:
            data = self._load() if self._cache is None else dict(self._cache)
            data[key] = json.loads(encoded)
            atomic_write_json(self._path, data)
            self._cache = data
            return data[key]

    def delete_key(self, key: str) -> bool:
        """Remove ``key`` (back to the frontend default). True if it existed."""
        validate_key(key)
        with self._lock:
            data = self._load() if self._cache is None else dict(self._cache)
            if key not in data:
                return False
            del data[key]
            atomic_write_json(self._path, data)
            self._cache = data
            return True

    def invalidate(self) -> None:
        with self._lock:
            self._cache = None


__all__ = [
    "UiSettingsStore",
    "InvalidSettingKeyError",
    "SettingValueTooLargeError",
    "validate_key",
    "KEY_PATTERN",
    "MAX_VALUE_BYTES",
]
