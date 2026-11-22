"""``/api/v1/ztilt`` — Z tilt adjust (`.agent/component/z_tilt.md`)."""
from __future__ import annotations

from fastapi import APIRouter

from mappers.z_tilt.ZTiltMapper import ZTiltMapper
from models.ZTiltModels import ZTiltStatus
from services.motion.HomingRoutineService import get_homing_routine_service
from services.program.MacroExecutionService import get_macro_execution_service
from services.motion.ZTiltService import get_z_tilt_service

router = APIRouter(prefix="/api/v1/ztilt", tags=["ztilt"])


def _status() -> ZTiltStatus:
    return ZTiltMapper.to_response(get_z_tilt_service().state())


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
