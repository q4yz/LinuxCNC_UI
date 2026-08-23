from typing import Dict, Any

from core.field_masking import ResponseTier, include_static
from dtos.axis.axis_dtos import AxisStateDTO
from models.axis_model import AxisStateResponse


class AxisMapper:
    """Converts between ``hardware.json`` v2.1 axis records and the
    runtime ``AxisStateDTO`` / ``AxisStateResponse`` pair.

    The compiler emits ``hardware.json`` axes with ``joint_number``
    (primary) and ``joint_numbers`` (list). The runtime mapper
    copies them straight onto the DTO and onto the Pydantic response,
    preserving the v2.1 wire shape end-to-end. The previous
    ``id`` string handle was removed in v2.1.
    """

    @classmethod
    def from_dict_to_dto(cls, data: Dict[str, Any]) -> AxisStateDTO:
        return AxisStateDTO(
            joint_number=int(data.get("joint_number", 0)),
            joint_numbers=list(data.get("joint_numbers", [])),
            min_limit=float(data.get("position_min", 0.0)),
            max_limit=float(data.get("position_max", 0.0)),
        )

    @classmethod
    def to_response(cls, dto: AxisStateDTO, r: ResponseTier = ResponseTier.ALL) -> AxisStateResponse:
        return AxisStateResponse(
            joint_number=dto.joint_number,
            joint_numbers=include_static(dto.joint_numbers, r),
            min_limit=include_static(dto.min_limit, r),
            max_limit=include_static(dto.max_limit, r),
        )
