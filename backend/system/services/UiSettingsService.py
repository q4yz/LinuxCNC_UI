"""Central UI settings — service between ``routers/ui_settings.py`` and
:class:`core.UiSettingsStore.UiSettingsStore`.

Translates store errors into HTTP errors (bad key / oversized value →
400, unset key → 404) so the router stays a thin edge.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from core.UiSettingsStore import (
    InvalidSettingKeyError,
    SettingValueTooLargeError,
    UiSettingsStore,
)
from domain_file_services.paths import UI_SETTINGS_FILE
from exceptions import BadRequestError, NotFoundError


class UiSettingsService:
    def __init__(self, store: UiSettingsStore) -> None:
        self._store = store

    def read_all(self) -> Dict[str, Any]:
        return self._store.read_all()

    def read(self, key: str) -> Any:
        try:
            if not self._store.has_key(key):
                raise NotFoundError(f"Setting {key!r} is not set")
            return self._store.read_key(key)
        except InvalidSettingKeyError as exc:
            raise BadRequestError(str(exc)) from exc

    def write(self, key: str, value: Any) -> Any:
        """Persist ``value`` and return what was stored (the echo)."""
        try:
            return self._store.write_key(key, value)
        except (InvalidSettingKeyError, SettingValueTooLargeError) as exc:
            raise BadRequestError(str(exc)) from exc

    def reset(self, key: str) -> None:
        try:
            self._store.delete_key(key)
        except InvalidSettingKeyError as exc:
            raise BadRequestError(str(exc)) from exc


_SERVICE_INSTANCE: Optional[UiSettingsService] = None


def get_ui_settings_service() -> UiSettingsService:
    """Process-wide service (lazy). Tests swap it via :func:`set_ui_settings_service`."""
    global _SERVICE_INSTANCE
    if _SERVICE_INSTANCE is None:
        _SERVICE_INSTANCE = UiSettingsService(UiSettingsStore(UI_SETTINGS_FILE))
    return _SERVICE_INSTANCE


def set_ui_settings_service(service: Optional[UiSettingsService]) -> None:
    global _SERVICE_INSTANCE
    _SERVICE_INSTANCE = service


__all__ = ["UiSettingsService", "get_ui_settings_service", "set_ui_settings_service"]
