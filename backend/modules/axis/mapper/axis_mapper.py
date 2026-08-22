from typing import Dict, Any

from modules.axis.dtos.axis_dtos import AxisStateDTO
from modules.axis.models.axis_model import AxisStateResponse


class AxisMapper:


    @classmethod
    def from_dict_to_dto(cls, data: Dict[str, Any]) -> AxisStateDTO:
        min_limit = float(data.get("position_min", 0.0))
        max_limit = float(data.get("position_max", 0.0))
        joints = data.get("joint_numbers", [])


        return AxisStateDTO(
            id=str(data.get("id", "")),
            joints=joints,
            min_limit=min_limit,
            max_limit=max_limit
        )

    @classmethod
    def from_dto_to_response(cls, dto: AxisStateDTO) -> AxisStateResponse:
        return AxisStateResponse(
            id=dto.id,
            joints=dto.joints,
            min_limit=dto.min_limit,
            max_limit=dto.max_limit
        )