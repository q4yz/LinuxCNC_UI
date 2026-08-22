
from typing import Generic, TypeVar, Optional, Any
from pydantic import BaseModel

T = TypeVar("T")

class WSEnvelope(BaseModel, Generic[T]):
    """Generic WebSocket Envelope pattern for telemetry broadcasts."""
    type: str
    data: T

class ServoThreadStateResponse(BaseModel):
    """
    Data Transfer Object for LinuxCNC state.
    All fields are Optional to support minimal 'diff' payloads.
    """
    task_state: Optional[int] = None
    estop: Optional[int] = None
    task_mode: Optional[int] = None

    position: Optional[tuple[float, ...]] = None
    actual_position: Optional[tuple[float, ...]] = None
    relative_position: Optional[tuple[float, ...]] = None

    state: Optional[int] = None
    file: Optional[str] = None
    homed: Optional[tuple[int, ...]] = None

    interp_state: Optional[int] = None
    g5x_index: Optional[int] = None

    g5x_offset: Optional[tuple[float, ...]] = None
    g92_offset: Optional[tuple[float, ...]] = None
    current_line: Optional[int] = None
    total_lines: Optional[int] = None

    errors: Optional[list[Any]] = None