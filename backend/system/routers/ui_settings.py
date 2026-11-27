"""``/api/v1/settings`` — the central UI settings store.

Served by the system service so settings stay available while the
machine backend is offline. See ``services/UiSettingsService.py`` and
``core/UiSettingsStore.py``.

Per caller: an admin reads and writes the shared set; a user reads it with
their own changes on top and writes their own; viewers and the agent read
the shared set (``UiSettingsService.*_for``).
"""
from __future__ import annotations

from fastapi import APIRouter, Path, Request, Response

from core.auth import current_user

from models.UiSettingsModels import (
    UiSettingResponse,
    UiSettingsListResponse,
    UiSettingValue,
)
from services.UiSettingsService import MACHINE_KEYS, get_ui_settings_service

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])

_KEY = Path(..., description="Namespaced setting key, e.g. 'camera.ip_camera_url'.")


@router.get(
    "",
    response_model=UiSettingsListResponse,
    summary="List UI settings",
    operation_id="listSettings",
)
def list_settings(request: Request) -> UiSettingsListResponse:
    user = current_user(request)
    service = get_ui_settings_service()
    return UiSettingsListResponse(values=service.read_all_for(user.name, user.role),
                                  personal=service.personal_keys(user.name, user.role),
                                  machine_keys=list(MACHINE_KEYS))


@router.get(
    "/{key}",
    response_model=UiSettingResponse,
    summary="Read one UI setting",
    description="Fresh read of one setting (used for `critical` settings). 404 when it was never set.",
    operation_id="readSetting",
    responses={404: {"description": "Setting was never set — the frontend default applies."}},
)
def read_setting(request: Request, key: str = _KEY) -> UiSettingResponse:
    user = current_user(request)
    return UiSettingResponse(key=key, value=get_ui_settings_service().read_for(user.name, user.role, key))


@router.put(
    "/{key}",
    response_model=UiSettingResponse,
    summary="Write one UI setting",
    description="Persists the value and echoes it back — the echo is the frontend's confirmation. An admin "
                "writes the shared set, a user their own (403 for a machine-wide key).",
    operation_id="writeSetting",
    responses={403: {"description": "A machine-wide setting: only an admin changes it."}},
)
def write_setting(request: Request, body: UiSettingValue, key: str = _KEY) -> UiSettingResponse:
    user = current_user(request)
    return UiSettingResponse(key=key, value=get_ui_settings_service().write_for(user.name, user.role, key, body.value))


@router.delete(
    "/{key}",
    status_code=204,
    summary="Reset one UI setting",
    description="A user: their own value removed, the admin's applies again. An admin: the shared value "
                "removed, the frontend default applies. Idempotent.",
    operation_id="resetSetting",
)
def reset_setting(request: Request, key: str = _KEY) -> Response:
    user = current_user(request)
    get_ui_settings_service().reset_for(user.name, user.role, key)
    return Response(status_code=204)


__all__ = ["router"]
