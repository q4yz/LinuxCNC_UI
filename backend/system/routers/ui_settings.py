"""``/api/v1/settings`` — the central UI settings store.

Served by the system service so settings stay available while the
machine backend is offline. See ``core/UiSettingsStore.py``.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Path, Response

from core.UiSettingsStore import (
    InvalidSettingKeyError,
    SettingValueTooLargeError,
    UiSettingsStore,
)
from domain_file_services.paths import UI_SETTINGS_FILE
from models.UiSettingsModels import (
    UiSettingResponse,
    UiSettingsListResponse,
    UiSettingValue,
)

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])

_store: Optional[UiSettingsStore] = None


def get_ui_settings_store() -> UiSettingsStore:
    """Process-wide store (lazy). Tests swap it via :func:`set_ui_settings_store`."""
    global _store
    if _store is None:
        _store = UiSettingsStore(UI_SETTINGS_FILE)
    return _store


def set_ui_settings_store(store: Optional[UiSettingsStore]) -> None:
    global _store
    _store = store


_KEY = Path(..., description="Namespaced setting key, e.g. 'camera.ip_camera_url'.")


def _bad_key(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.get(
    "",
    response_model=UiSettingsListResponse,
    summary="List UI settings",
    operation_id="listSettings",
)
def list_settings() -> UiSettingsListResponse:
    return UiSettingsListResponse(values=get_ui_settings_store().read_all())


@router.get(
    "/{key}",
    response_model=UiSettingResponse,
    summary="Read one UI setting",
    description="Fresh read of one setting (used for `critical` settings). 404 when it was never set.",
    operation_id="readSetting",
    responses={404: {"description": "Setting was never set — the frontend default applies."}},
)
def read_setting(key: str = _KEY) -> UiSettingResponse:
    store = get_ui_settings_store()
    try:
        if not store.has_key(key):
            raise HTTPException(status_code=404, detail=f"Setting {key!r} is not set")
        return UiSettingResponse(key=key, value=store.read_key(key))
    except InvalidSettingKeyError as exc:
        raise _bad_key(exc)


@router.put(
    "/{key}",
    response_model=UiSettingResponse,
    summary="Write one UI setting",
    description="Persists the value and echoes it back — the echo is the frontend's confirmation.",
    operation_id="writeSetting",
)
def write_setting(body: UiSettingValue, key: str = _KEY) -> UiSettingResponse:
    try:
        stored = get_ui_settings_store().write_key(key, body.value)
    except (InvalidSettingKeyError, SettingValueTooLargeError) as exc:
        raise _bad_key(exc)
    return UiSettingResponse(key=key, value=stored)


@router.delete(
    "/{key}",
    status_code=204,
    summary="Reset one UI setting",
    description="Removes the stored value so the frontend default applies again. Idempotent.",
    operation_id="resetSetting",
)
def reset_setting(key: str = _KEY) -> Response:
    try:
        get_ui_settings_store().delete_key(key)
    except InvalidSettingKeyError as exc:
        raise _bad_key(exc)
    return Response(status_code=204)


__all__ = ["router", "get_ui_settings_store", "set_ui_settings_store"]
