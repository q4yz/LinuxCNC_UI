from typing import Dict, Any

from core.field_masking import ResponseTier, include_static
from dtos.axis.axis_dtos import AxisStateDTO
from models.axis_model import AxisStateResponse


class AxisMapper:
    """Converts between ``hardware.json`` axis records and the
    runtime ``AxisStateDTO`` / ``AxisStateResponse`` pair.

    The compiler emits ``hardware.json`` axes with a string ``id``
    (the canonical LinuxCNC letter — ``x``, ``y``, ``z``, ``a``, ...)
    plus a ``joint_numbers`` list of every driving joint. The runtime
    mapper copies those fields straight onto the DTO and onto the
    Pydantic response.
    """

    @classmethod
    def from_dict_to_dto(cls, data: Dict[str, Any]) -> AxisStateDTO:
        return AxisStateDTO(
            id=str(data.get("id", "")),
            joint_numbers=list(data.get("joint_numbers", [])),
            min_limit=float(data.get("position_min", 0.0)),
            max_limit=float(data.get("position_max", 0.0)),
        )

    @classmethod
    def to_response(cls, dto: AxisStateDTO, r: ResponseTier = ResponseTier.ALL) -> AxisStateResponse:
        return AxisStateResponse(
            id=dto.id,
            joint_numbers=include_static(dto.joint_numbers, r),
            min_limit=include_static(dto.min_limit, r),
            max_limit=include_static(dto.max_limit, r),
        )
