from typing import Any, Dict

from core.field_masking import ResponseTier, include_static
from dtos.mcu.McuDto import McuPins
from dtos.pins.HalPin import HalDataType
from dtos.pins.ReadWriteDynamicHalPin import ReadWriteDynamicHalPin
from models.McuModels import McuStateResponse

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

    @staticmethod
    def is_resettable(data: Dict[str, Any]) -> bool:
        """A Remora MCU that declared a ``reset_pin`` — the one rule both
        the runtime (this mapper) and the HAL compiler's
        ``webgui_connections.hal`` binding use."""
        return (
            bool(data.get("id"))
            and str(data.get("connection", "")) in REMORA_CONNECTIONS
            and bool(data.get("reset_pin"))
        )

    @classmethod
    def from_dict_to_McuPins(cls, data: Dict[str, Any]) -> McuPins:
        """Build one MCU's runtime surface.

        Only a Remora MCU that declared a ``reset_pin`` gets a real
        ``webgui.<id>-reset`` pin — ``ReadWriteDynamicHalPin`` (HAL_OUT),
        driven by webgui and pulsed by ``McuService.reset_mcus``. It is
        wired to the board in ``webgui_connections.hal``
        (``McuResetWebguiMapper``: ``=> remora.PRU-reset``).
        """
        mcu_id = str(data.get("id", ""))
        connection = str(data.get("connection", ""))
        if not cls.is_resettable(data):
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
