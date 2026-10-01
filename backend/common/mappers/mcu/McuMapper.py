from typing import Any, Dict

from core.field_masking import ResponseTier, include_static
from dtos.mcu.McuDto import McuPins
from dtos.pins.HalPin import HalDataType
from dtos.pins.ReadWriteDynamicHalPin import ReadWriteDynamicHalPin
from models.mcu_model import McuStateResponse

#: Connections whose boards can carry a `reset_pin` — the same set the
#: `.cfg` parser accepts `reset_pin` on (`machineconfig_schema.py`).
REMORA_CONNECTIONS = frozenset({"remora-spi", "remora-eth"})


class McuMapper:
    """Converts ``hardware.json`` ``mcus[]`` records into the runtime
    ``McuPins`` DTO and the ``McuStateResponse`` wire model."""

    @staticmethod
    def reset_pin_name(mcu_id: str) -> str:
        """``webgui.<id>-reset`` (without the ``webgui.`` component prefix)."""
        return f"{mcu_id}-reset"

    @classmethod
    def from_dict_to_McuPins(cls, data: Dict[str, Any]) -> McuPins:
        """Build one MCU's runtime surface.

        Only a Remora MCU that declared a ``reset_pin`` gets a real
        ``webgui.<id>-reset`` pin — ``ReadWriteDynamicHalPin`` (HAL_OUT),
        driven by webgui and pulsed by ``McuService.reset_mcus``. Wiring
        that pin to the board in ``machine.hal`` is the HAL compiler's
        job (not done yet), so for now it is a registered but
        unconnected HAL pin.
        """
        mcu_id = str(data.get("id", ""))
        connection = str(data.get("connection", ""))
        resettable = bool(mcu_id) and connection in REMORA_CONNECTIONS and bool(data.get("reset_pin"))
        if not resettable:
            return McuPins(id=mcu_id, connection=connection)
        return McuPins(
            id=mcu_id,
            connection=connection,
            resettable=True,
            reset=ReadWriteDynamicHalPin(
                cls.reset_pin_name(mcu_id), HalDataType.BIT, f"Reset request for MCU '{mcu_id}' (pulsed)",
            ),
        )

    @classmethod
    def to_response(cls, dto: McuPins, r: ResponseTier = ResponseTier.ALL) -> McuStateResponse:
        return McuStateResponse(
            id=dto.id,
            connection=include_static(dto.connection, r),
            resettable=include_static(dto.resettable, r),
        )


__all__ = ["McuMapper", "REMORA_CONNECTIONS"]
