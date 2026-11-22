"""Z tilt API models (``/api/v1/ztilt``)."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class ZTiltStatus(BaseModel):
    configured: bool = Field(..., description="The machine has a [z_tilt] section.")
    running: bool = Field(..., description="An adjust is running (started here).")
    offsets: List[float] = Field(default_factory=list, description="Each Z motor's offset (mm).")
    spread: Optional[float] = Field(None, description="Probed height spread of the last round (mm).")


__all__ = ["ZTiltStatus"]
