from typing import Any, Optional

from dtos.servo_thread_state import ServoThreadStateDTO
from models.servo_thread import ServoThreadStateResponse


class ServoThreadStateMapper:

    @staticmethod
    def from_stat(machine_stat: Any, errors: list[Any] = None) -> ServoThreadStateDTO:
        """
        Creates a FULL state DTO directly from the raw hardware stat.
        (We populate all fields so we have a complete baseline to diff against).
        """
        if errors is None:
            errors = []

        if machine_stat is None:
            # Safe offline defaults
            return ServoThreadStateDTO(
                task_state=0, estop=1, task_mode=0,
                position=(0.0,) * 9, actual_position=(0.0,) * 9, relative_position=(0.0,) * 9,
                state=0, file="", homed=(0, 0, 0), interp_state=1, g5x_index=1,
                g5x_offset=(0.0,) * 9, g92_offset=(0.0,) * 9, current_line=0, total_lines=0,
                errors=errors
            )

        actual_position = getattr(machine_stat, 'actual_position', (0.0,) * 9)
        g5x_offset = getattr(machine_stat, 'g5x_offset', (0.0,) * 9)
        g92_offset = getattr(machine_stat, 'g92_offset', (0.0,) * 9)
        tool_offset = getattr(machine_stat, 'tool_offset', (0.0,) * 9)

        relative_position = []
        for i in range(len(actual_position)):
            g5x = g5x_offset[i] if g5x_offset and i < len(g5x_offset) else 0.0
            g92 = g92_offset[i] if g92_offset and i < len(g92_offset) else 0.0
            tool = tool_offset[i] if tool_offset and i < len(tool_offset) else 0.0

            relative_position.append(actual_position[i] - g5x - g92 - tool)

        return ServoThreadStateDTO(
            task_state=getattr(machine_stat, 'task_state', 0),
            estop=getattr(machine_stat, 'estop', 1),
            task_mode=getattr(machine_stat, 'task_mode', 0),
            position=getattr(machine_stat, 'position', (0.0,) * 9),
            actual_position=actual_position,
            relative_position=tuple(relative_position),
            state=getattr(machine_stat, 'state', 0),
            file=getattr(machine_stat, 'file', ""),
            homed=getattr(machine_stat, 'homed', (0, 0, 0)),
            interp_state=getattr(machine_stat, 'interp_state', 1),
            g5x_index=getattr(machine_stat, 'g5x_index', 1),
            g5x_offset=g5x_offset,
            g92_offset=g92_offset,
            current_line=getattr(machine_stat, 'current_line', 0),
            total_lines=getattr(machine_stat, 'total_lines', 0),
            errors=errors,
        )

    @staticmethod
    def get_diff_response(new_state: ServoThreadStateDTO, old_state: Optional[ServoThreadStateDTO]) -> ServoThreadStateResponse:
        """
        Compares two DTOs and returns a minimal DTO containing ONLY the changed fields.
        """
        if old_state is None:
            return ServoThreadStateMapper.to_response(new_state)

        diff_data = {}

        new_dict = new_state.model_dump()
        old_dict = old_state.model_dump()

        for key, new_val in new_dict.items():
            old_val = old_dict.get(key)

            if new_val != old_val:
                diff_data[key] = new_val

        return ServoThreadStateResponse(**diff_data)

    @staticmethod
    def to_response(dto: ServoThreadStateDTO) -> ServoThreadStateResponse:
        """
        One-to-one mapper from internal DTO to the API Response model.
        """
        return ServoThreadStateResponse(**dto.model_dump())