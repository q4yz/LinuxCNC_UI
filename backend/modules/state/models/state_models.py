from typing import List, Literal
from pydantic import BaseModel, Field

class StateCommand(BaseModel):
    state: Literal["on", "off", "estop", "estop_reset"] = Field(
        ...,
        description="Target machine state.",
    )

class ModeCommand(BaseModel):
    mode: Literal["manual", "auto", "mdi"] = Field(
        ...,
        description="Target task mode.",
    )

class MdiCommand(BaseModel):
    command: str = Field(..., description="G-code / MDI command string to execute")

class StateSnapshotResponse(BaseModel):
    """Clean + diagnostic machine-state snapshot for ``GET /state``."""
    state: str = Field(
        ...,
        description="Clean MachineState enum value (e.g. 'idle', 'running').",
    )
    raw_task_state: int = Field(..., description="linuxcnc NML task_state (diagnostic only).")
    raw_estop: int = Field(..., description="linuxcnc NML estop bit (diagnostic only).")
    raw_interp_state: int = Field(..., description="linuxcnc NML interp_state (diagnostic only).")
    file: str = Field(default="", description="Loaded G-code file path; empty when none.")
    homed: List[int] = Field(..., description="Per-axis homed flags (one entry per axis).")

class StatusResponse(BaseModel):
    status: str = Field(default="success", description="Outcome summary (e.g., 'success')")