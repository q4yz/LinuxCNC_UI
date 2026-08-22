# ==========================================
# 2. FastAPI Output Payload (Response)
# ==========================================
from typing import List

from pydantic import BaseModel, Field


class AxisStateResponse(BaseModel):
    """JSON response model for axis configuration."""
    id: str = Field(..., description="Axis identifier (e.g., 'x', 'y', 'z')")
    joints: List[int] = Field(..., description="List of joint numbers (e.g., [1, 2] for a dual-motor Y axis)")
    min_limit: float = Field(..., description="Minimum soft limit for the axis")
    max_limit: float = Field(..., description="Maximum soft limit for the axis")