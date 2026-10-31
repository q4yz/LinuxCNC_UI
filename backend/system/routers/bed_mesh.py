"""``/api/v1/modules/bedmesh`` — saved bed meshes and the active one.

Files only, so this lives in the always-up system service; switching
compensation on / off is the machine backend's
(``/api/v1/bedmesh/enable``, a HAL pin). See ``BedMeshService``.
"""
from __future__ import annotations

from fastapi import APIRouter, Path

from models.BedMeshModels import (
    BedMeshCreateRequest,
    BedMeshDefaults,
    BedMeshGrid,
    BedMeshListResponse,
)
from services.BedMeshService import get_bed_mesh_service

router = APIRouter(prefix="/api/v1/modules/bedmesh", tags=["modules:bedmesh"])

_NAME = Path(..., description="Mesh name (its file name without .txt).")


@router.get("/meshes", response_model=BedMeshListResponse, operation_id="listBedMeshes",
            summary="List bed meshes")
def list_meshes() -> BedMeshListResponse:
    return get_bed_mesh_service().list()


@router.get("/defaults", response_model=BedMeshDefaults, operation_id="getBedMeshDefaults",
            summary="Grid for a new mesh (probe_count over the X / Y limits)")
def get_defaults() -> BedMeshDefaults:
    return get_bed_mesh_service().defaults()


@router.post("/meshes", response_model=BedMeshGrid, operation_id="createBedMesh",
             summary="Create a flat (all zero) mesh", responses={409: {"description": "Name taken."}})
def create_mesh(payload: BedMeshCreateRequest) -> BedMeshGrid:
    return get_bed_mesh_service().create(payload.name, payload)


@router.get("/meshes/{name}", response_model=BedMeshGrid, operation_id="readBedMesh",
            summary="Read a bed mesh")
def read_mesh(name: str = _NAME) -> BedMeshGrid:
    return get_bed_mesh_service().read(name)


@router.put("/meshes/{name}", response_model=BedMeshGrid, operation_id="saveBedMesh",
            summary="Save (create or overwrite) a bed mesh")
def save_mesh(payload: BedMeshGrid, name: str = _NAME) -> BedMeshGrid:
    return get_bed_mesh_service().save(payload.model_copy(update={"name": name}))


@router.delete("/meshes/{name}", response_model=BedMeshListResponse, operation_id="deleteBedMesh",
               summary="Delete a bed mesh", responses={409: {"description": "It is the active mesh."}})
def delete_mesh(name: str = _NAME) -> BedMeshListResponse:
    service = get_bed_mesh_service()
    service.delete(name)
    return service.list()


@router.post("/meshes/{name}/activate", response_model=BedMeshListResponse,
             operation_id="activateBedMesh", summary="Use this mesh for compensation")
def activate_mesh(name: str = _NAME) -> BedMeshListResponse:
    return get_bed_mesh_service().activate(name)
