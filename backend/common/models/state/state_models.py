from typing import List
from pydantic import BaseModel, Field

# ``state`` / ``mode`` are plain ``str`` rather than a ``Literal`` —
# an unrecognised value must reach ``StateService._resolve`` and come
# back as the router's hand-translated ``400 Invalid state`` /
# ``400 Invalid mode`` (pinned by test_machine_state_module.py). A
# ``Literal`` would make FastAPI reject it at the validation layer
# with a ``422`` before the handler ever runs, silently changing the
# documented contract.
class StateCommand(BaseModel):
    state: str = Field(
        ...,
        description="Target machine state: 'on', 'off', 'estop', or 'estop_reset'.",
    )

class ModeCommand(BaseModel):
    mode: str = Field(
        ...,
        description="Target task mode: 'manual', 'auto', or 'mdi'.",
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