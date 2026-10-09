"""``/api/v1/settings`` — the central UI settings store.

Served by the system service so settings stay available while the
machine backend is offline. See ``services/UiSettingsService.py`` and
``core/UiSettingsStore.py``.
"""
from __future__ import annotations

from fastapi import APIRouter, Path, Response

from models.UiSettingsModels import (
    UiSettingResponse,
    UiSettingsListResponse,
    UiSettingValue,
)
from services.UiSettingsService import get_ui_settings_service

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])

_KEY = Path(..., description="Namespaced setting key, e.g. 'camera.ip_camera_url'.")


@router.get(
    "",
    response_model=UiSettingsListResponse,
    summary="List UI settings",
    operation_id="listSettings",
)
def list_settings() -> UiSettingsListResponse:
    return UiSettingsListResponse(values=get_ui_settings_service().read_all())


@router.get(
    "/{key}",
    response_model=UiSettingResponse,
    summary="Read one UI setting",
    description="Fresh read of one setting (used for `critical` settings). 404 when it was never set.",
    operation_id="readSetting",
    responses={404: {"description": "Setting was never set — the frontend default applies."}},
)
def read_setting(key: str = _KEY) -> UiSettingResponse:
    return UiSettingResponse(key=key, value=get_ui_settings_service().read(key))


@router.put(
    "/{key}",
    response_model=UiSettingResponse,
    summary="Write one UI setting",
    description="Persists the value and echoes it back — the echo is the frontend's confirmation.",
    operation_id="writeSetting",
)
def write_setting(body: UiSettingValue, key: str = _KEY) -> UiSettingResponse:
    return UiSettingResponse(key=key, value=get_ui_settings_service().write(key, body.value))


@router.delete(
    "/{key}",
    status_code=204,
    summary="Reset one UI setting",
    description="Removes the stored value so the frontend default applies again. Idempotent.",
    operation_id="resetSetting",
)
def reset_setting(key: str = _KEY) -> Response:
    get_ui_settings_service().reset(key)
    return Response(status_code=204)


__all__ = ["router"]
