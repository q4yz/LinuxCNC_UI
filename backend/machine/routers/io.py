"""``/api/v1/modules/io`` — fans, output pins and input pins (``IoService``)."""
from __future__ import annotations

from fastapi import APIRouter, Path

from models.IoModels import IoSetRequest, IoState
from services.IoService import get_io_service

router = APIRouter(prefix="/api/v1/modules/io", tags=["modules:io"])


@router.get("", response_model=IoState, operation_id="getIoState",
            summary="Fans, output pins and input pins with their values")
def get_io_state() -> IoState:
    return get_io_service().state()


@router.put("/{pin_id}", response_model=IoState, operation_id="setIoValue",
            summary="Set a fan (%) or an output pin",
            responses={404: {"description": "No such fan or output."}, 400: {"description": "An input."}})
def set_io_value(payload: IoSetRequest, pin_id: str = Path(..., description="Fan or output pin id.")) -> IoState:
    return get_io_service().set_value(pin_id, payload.value)


__all__ = ["router"]
