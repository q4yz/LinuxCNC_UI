"""``/api/v1/bedmesh`` — bed mesh compensation on / off (a HAL pin, so
the machine backend). The meshes are system-service files:
``/api/v1/modules/bedmesh``."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from services.BedMeshService import get_bed_mesh_service

router = APIRouter(prefix="/api/v1/bedmesh", tags=["bedmesh"])


class BedMeshEnable(BaseModel):
    enabled: bool = Field(..., description="Z compensation from the active mesh is on.")


@router.get("/enable", response_model=BedMeshEnable, operation_id="getBedMeshEnable",
            summary="Is bed mesh compensation on?")
def get_enable() -> BedMeshEnable:
    return BedMeshEnable(enabled=get_bed_mesh_service().is_enabled())


@router.put("/enable", response_model=BedMeshEnable, operation_id="setBedMeshEnable",
            summary="Switch bed mesh compensation on / off")
def set_enable(payload: BedMeshEnable) -> BedMeshEnable:
    return BedMeshEnable(enabled=get_bed_mesh_service().set_enabled(payload.enabled))


__all__ = ["router"]
