from pydantic import BaseModel, Field
from typing import Any


class ServoThreadStateDTO(BaseModel):

    task_state: int = Field(default=0, description="1 = ESTOP, 2 = ESTOP_RESET, 3 = OFF, 4 = ON")
    estop: int = Field(default=1, description="1 = Active, 0 = Clear")
    task_mode: int = Field(default=0, description="1 = Manual, 2 = Auto, 3 = MDI")

    position: tuple[float, ...] = Field(default=(0.0,) * 9)
    actual_position: tuple[float, ...] = Field(default=(0.0,) * 9)
    relative_position: tuple[float, ...] = Field(default=(0.0,) * 9)

    state: int = Field(default=0)
    file: str = Field(default="")
    homed: tuple[int, ...] = Field(default=(0, 0, 0))

    interp_state: int = Field(default=1, description="1=IDLE, 2=RUNNING, 3=PAUSED, 4=WAITING")
    g5x_index: int = Field(default=1)

    g5x_offset: tuple[float, ...] = Field(default=(0.0,) * 9)
    g92_offset: tuple[float, ...] = Field(default=(0.0,) * 9)
    current_line: int = Field(default=0)
    total_lines: int = Field(default=0)

    errors: list[Any] = Field(default_factory=list)

