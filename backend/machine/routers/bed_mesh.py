"""``/api/v1/bedmesh`` — bed mesh compensation on / off (a HAL pin, so
the machine backend). The meshes are system-service files:
``/api/v1/modules/bedmesh``."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from mappers.bed_mesh.BedMeshMapper import BedMeshMapper
from models.BedMeshModels import BedMeshEnable
from services.motion.BedMeshProbeService import DEFAULT_PROFILE, get_bed_mesh_probe_service, parse_command
from services.motion.BedMeshService import get_bed_mesh_service

router = APIRouter(prefix="/api/v1/bedmesh", tags=["bedmesh"])


@router.get("/enable", response_model=BedMeshEnable, operation_id="getBedMeshEnable",
            summary="Is bed mesh compensation on?")
def get_enable() -> BedMeshEnable:
    return BedMeshMapper.to_response(get_bed_mesh_service().state())


@router.put("/enable", response_model=BedMeshEnable, operation_id="setBedMeshEnable",
            summary="Switch bed mesh compensation on / off")
def set_enable(payload: BedMeshEnable) -> BedMeshEnable:
    get_bed_mesh_service().set_enabled(payload.enabled)
    return BedMeshMapper.to_response(get_bed_mesh_service().state())


class BedMeshCalibrate(BaseModel):
    profile: str = Field(DEFAULT_PROFILE, description="Mesh name to save the probed mesh as (Klipper's PROFILE).")


class BedMeshCalibrateStatus(BaseModel):
    running: bool = Field(..., description="Probing is running (progress in the console).")


@router.post("/calibrate", response_model=BedMeshCalibrateStatus, operation_id="calibrateBedMesh",
             summary="Probe the bed mesh (BED_MESH_CALIBRATE), save and activate it",
             responses={400: {"description": "No [bed_mesh], not homed, ..."}, 409: {"description": "Busy."}})
def calibrate(payload: BedMeshCalibrate) -> BedMeshCalibrateStatus:
    from services.motion import LevelingService
    from services.motion.HomingRoutineService import get_homing_routine_service
    from services.program.MacroExecutionService import get_macro_execution_service
    from services.motion.ZTiltService import get_z_tilt_service

    profile = parse_command(f"BED_MESH_CALIBRATE PROFILE={payload.profile}") or DEFAULT_PROFILE
    busy = (get_macro_execution_service().is_running() or get_homing_routine_service().is_running()
            or get_z_tilt_service().is_running() or LevelingService.is_running())
    service = get_bed_mesh_probe_service()
    service.start(profile, busy=busy)
    return BedMeshCalibrateStatus(running=service.is_running())


@router.get("/calibrate", response_model=BedMeshCalibrateStatus, operation_id="getBedMeshCalibrate",
            summary="Is the bed mesh being probed?")
def calibrate_status() -> BedMeshCalibrateStatus:
    return BedMeshCalibrateStatus(running=get_bed_mesh_probe_service().is_running())


__all__ = ["router"]
