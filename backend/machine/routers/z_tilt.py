"""``/api/v1/ztilt`` — Z tilt adjust (`.agent/component/z_tilt.md`)."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from services.HomingRoutineService import get_homing_routine_service
from services.MacroExecutionService import get_macro_execution_service
from services.ZTiltService import get_z_tilt_service

router = APIRouter(prefix="/api/v1/ztilt", tags=["ztilt"])


class ZTiltStatus(BaseModel):
    configured: bool = Field(..., description="The machine has a [z_tilt] section.")
    running: bool = Field(..., description="An adjust is running (started here).")
    offsets: List[float] = Field(default_factory=list, description="Each Z motor's offset (mm).")
    spread: Optional[float] = Field(None, description="Probed height spread of the last round (mm).")


def _status() -> ZTiltStatus:
    service = get_z_tilt_service()
    return ZTiltStatus(
        configured=service.settings() is not None,
        running=service.is_running(),
        offsets=service.offsets(),
        spread=service.last_result.get("spread"),
    )


@router.get("/status", response_model=ZTiltStatus, operation_id="getZTiltStatus", summary="Z tilt state")
def get_status() -> ZTiltStatus:
    return _status()


@router.post("/adjust", response_model=ZTiltStatus, operation_id="startZTiltAdjust",
             summary="Probe and level the Z motors (runs in the background; progress in the console)")
def adjust() -> ZTiltStatus:
    busy = get_macro_execution_service().is_running() or get_homing_routine_service().is_running()
    get_z_tilt_service().start(busy=busy)
    return _status()


__all__ = ["router"]
