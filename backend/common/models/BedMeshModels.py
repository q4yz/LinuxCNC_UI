"""Bed mesh API models (``/api/v1/modules/bedmesh``, `.agent/component/bed_mesh.md`)."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class BedMeshGrid(BaseModel):
    """A probed mesh on a regular grid: ``z[row][col]`` is the Z offset
    (mm) at ``(xs[col], ys[row])``."""

    name: str = Field(..., description="Mesh name (its file name without .txt).")
    xs: List[float] = Field(..., description="Grid X coordinates, ascending.")
    ys: List[float] = Field(..., description="Grid Y coordinates, ascending.")
    z: List[List[float]] = Field(..., description="Z offsets per row (one row per ys entry).")


class BedMeshListResponse(BaseModel):
    names: List[str] = Field(default_factory=list, description="Every saved mesh, sorted.")
    active: Optional[str] = Field(None, description="The mesh the compensation component uses.")


class BedMeshDefaults(BaseModel):
    """A new mesh's grid, from the default machine's ``hardware.json``:
    ``[bed_mesh] probe_count`` over the X / Y axis limits."""

    x_min: float = 0.0
    x_max: float = 200.0
    y_min: float = 0.0
    y_max: float = 200.0
    x_count: int = 3
    y_count: int = 3


class BedMeshCreateRequest(BedMeshDefaults):
    name: str = Field(..., description="Name of the new, flat (all zero) mesh.")
