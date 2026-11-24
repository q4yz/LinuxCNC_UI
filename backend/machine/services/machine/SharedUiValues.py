"""Operator UI values every client shows the same (#128).

A slider that only steers the browser (the jog speed, the extruder's
jog speed and distance, ...) has no machine pin to read back, so a
second client used to show its default. A client publishes the value
over the telemetry WebSocket (``{"type": "ui_value", "key", "value"}``);
this keeps the latest one and the socket broadcasts it to every client,
and hands the whole set to a client that connects later.

In memory only: the values describe the operators' current session,
not configuration (that is the settings store's job).
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

#: ``jog.speed``, ``extruder.tool0.speed``, ...
KEY_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
#: A bound on the store: the keys come from clients.
MAX_KEYS = 256
MAX_TEXT = 256


def _valid_value(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return value == value and value not in (float("inf"), float("-inf"))
    return isinstance(value, str) and len(value) <= MAX_TEXT


class SharedUiValues:
    def __init__(self) -> None:
        self._values: Dict[str, Any] = {}

    def set(self, key: Any, value: Any) -> Optional[Tuple[str, Any]]:
        """Store ``value``; returns ``(key, value)`` to broadcast, or None
        when the message is invalid or would grow the store past its bound."""
        if not isinstance(key, str) or not KEY_PATTERN.match(key) or not _valid_value(value):
            return None
        if key not in self._values and len(self._values) >= MAX_KEYS:
            return None
        self._values[key] = value
        return key, value

    def snapshot(self) -> Dict[str, Any]:
        return dict(self._values)


_INSTANCE: Optional[SharedUiValues] = None


def get_shared_ui_values() -> SharedUiValues:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = SharedUiValues()
    return _INSTANCE
