"""Central UI settings — service between ``routers/ui_settings.py`` and
:class:`core.UiSettingsStore.UiSettingsStore`.

Translates store errors into HTTP errors (bad key / oversized value →
400, unset key → 404) so the router stays a thin edge.

**Whose settings** (``*_for``): there is one shared set — what an admin
saves (``settings.json``, also what the backends read). A user (role
``user``) sees it with their own changes on top, kept in the user
database (``core.users_db``, ``user_settings``); resetting one of them
brings back the admin's. Viewers (anyone not logged in) and the agent
see the shared set only. :data:`MACHINE_KEYS` are machine-wide (a
backend reads them): only an admin changes them, for everyone.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from core.UiSettingsStore import (
    InvalidSettingKeyError,
    SettingValueTooLargeError,
    UiSettingsStore,
)
from domain_file_services.paths import UI_SETTINGS_FILE
from exceptions import BadRequestError, NotFoundError

#: Machine-wide settings (a backend reads them from the shared set): exact
#: keys, or a namespace ending in ".".
MACHINE_KEYS = ("camera.ip_camera_url", "camera.default_device_id", "assistant.", "slicer.")


def is_machine_key(key: str) -> bool:
    return any(key.startswith(k) if k.endswith(".") else key == k for k in MACHINE_KEYS)


def _personal(role: str) -> bool:
    """Whose writes are their own: users. An admin's are the shared set;
    viewers and the agent cannot write."""
    return role == "user"


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

    # -- per caller -------------------------------------------------------- #

    @staticmethod
    def _own(name: str, role: str) -> Dict[str, Any]:
        if not _personal(role):
            return {}
        from core.users_db import get_user_store

        return {k: v for k, v in get_user_store().settings(name).items() if not is_machine_key(k)}

    def read_all_for(self, name: str, role: str) -> Dict[str, Any]:
        return {**self.read_all(), **self._own(name, role)}

    def personal_keys(self, name: str, role: str) -> List[str]:
        return sorted(self._own(name, role))

    def read_for(self, name: str, role: str, key: str) -> Any:
        own = self._own(name, role)
        if key in own:
            return own[key]
        return self.read(key)

    def write_for(self, name: str, role: str, key: str, value: Any) -> Any:
        if not _personal(role):
            return self.write(key, value)
        if is_machine_key(key):
            raise HTTPException(403, f"{key!r} is set by the admin for the whole machine")
        from core.UiSettingsStore import MAX_VALUE_BYTES, validate_key
        import json

        try:
            validate_key(key)
        except InvalidSettingKeyError as exc:
            raise BadRequestError(str(exc)) from exc
        if len(json.dumps(value)) > MAX_VALUE_BYTES:
            raise BadRequestError(f"Setting {key!r} is larger than {MAX_VALUE_BYTES} bytes")
        from core.users_db import get_user_store

        get_user_store().set_setting(name, key, value)
        return value

    def reset_for(self, name: str, role: str, key: str) -> None:
        """A user: back to the admin's value; an admin: the shared value unset."""
        if not _personal(role):
            self.reset(key)
            return
        from core.users_db import get_user_store

        get_user_store().delete_setting(name, key)


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
