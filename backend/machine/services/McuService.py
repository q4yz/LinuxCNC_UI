import asyncio
import logging
from typing import List, Optional

from exceptions import ConflictError
from dtos.mcu.McuDto import McuPins
from mappers.mcu.McuMapper import McuMapper
from services.mcu_config_mapper import get_mcus

logger = logging.getLogger("backend.services.mcu")

#: How long ``webgui.<id>-reset`` is held high — same pulse width as
#: ``StateService.activate_estop``.
RESET_PULSE_S = 0.05


class McuService:
    """Owns every ``hardware.json`` MCU's runtime surface.

    Registers ``webgui.<id>-reset`` for each resettable (Remora +
    ``reset_pin``) MCU and pulses them on request. Connecting that pin
    to the board in ``machine.hal`` is the HAL compiler's job and not
    done yet — until then the pulse lands on an unconnected HAL pin.
    """

    def __init__(self) -> None:
        self._halpins_cache: Optional[List[McuPins]] = None

    def preload_hal_pins(self) -> None:
        """Queue every resettable MCU's pin. Call before ``HalPin.initialize_component()``."""
        if self._halpins_cache is not None:
            return
        self._halpins_cache = [McuMapper.from_dict_to_McuPins(mcu) for mcu in get_mcus()]
        logger.info(
            "Preloaded %d MCU(s), %d resettable.",
            len(self._halpins_cache),
            len(self.resettable_mcus()),
        )

    def get_halpins(self) -> List[McuPins]:
        if self._halpins_cache is None:
            logger.warning("get_halpins() called before preload! Forcing late initialization.")
            self.preload_hal_pins()
        return self._halpins_cache or []

    def resettable_mcus(self) -> List[McuPins]:
        return [mcu for mcu in (self._halpins_cache or []) if mcu.resettable]

    async def reset_mcus(self) -> List[str]:
        """Pulse ``webgui.<id>-reset`` on every resettable MCU at once.

        Returns the ids that were reset. Raises :class:`ConflictError`
        when the machine has no resettable MCU at all — the UI only
        offers the button when one exists, so this is a stale-UI case.
        """
        mcus = [mcu for mcu in self.get_halpins() if mcu.resettable]
        if not mcus:
            raise ConflictError("No resettable MCU — declare a `reset_pin` on a Remora `[mcu]` section.")

        for mcu in mcus:
            mcu.reset.set_value(True)
        await asyncio.sleep(RESET_PULSE_S)
        # Release the pin so it is armed for the next press.
        for mcu in mcus:
            mcu.reset.set_value(False)

        ids = [mcu.id for mcu in mcus]
        logger.info("Reset pulse sent to MCU(s): %s", ", ".join(ids))
        return ids


_mcu_service: Optional[McuService] = None


def get_mcu_service() -> McuService:
    """Lazy module-level singleton, matching ``get_fans_service``."""
    global _mcu_service
    if _mcu_service is None:
        _mcu_service = McuService()
    return _mcu_service


__all__ = ["McuService", "get_mcu_service", "RESET_PULSE_S"]
