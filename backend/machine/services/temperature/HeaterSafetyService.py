"""Heaters off when the machine leaves ON — and they stay off.

E-stop, power off, a fault that drops the machine out of ON (a joint
following error, the CAN status bit, ...): every heater target goes to 0.
The HAL loops already stop heating while the machine is off (each heater's
``heat-ok`` gate), but the target stayed — so powering back on resumed
heating on its own, unattended. Now nothing heats again until someone sets
a target (the UI, M104 / M140 of the next print). No automatic recovery.

Fed from the servo telemetry loop (10 Hz, runs with or without a browser).
"""
from __future__ import annotations

import logging
from typing import Optional

from hardware import linuxcnc
from services.machine.ConsoleLogger import LogLevel, get_console_logger
from services.temperature.HeaterService import HeaterService, get_heater_service

logger = logging.getLogger("backend.heater_safety")


class HeaterSafetyService:
    def __init__(self, heaters: Optional[HeaterService] = None) -> None:
        self._heaters = heaters
        self._was_on: Optional[bool] = None

    def observe(self, task_state: int) -> list[str]:
        """The machine's ``task_state``, every telemetry tick. On the step
        from ON to anything else: every heater target to 0; returns the ids
        of the heaters that had one (empty otherwise)."""
        on = task_state == getattr(linuxcnc, "STATE_ON", 4)
        left_on = self._was_on is True and not on
        self._was_on = on
        if not left_on:
            return []
        heaters = self._heaters or get_heater_service()
        try:
            turned_off = heaters.all_off()
        except Exception:  # noqa: BLE001 - logged; the next drop tries again
            logger.exception("Could not turn the heaters off")
            return []
        if turned_off:
            get_console_logger().log_event(
                f"Machine is off: heaters turned off ({', '.join(turned_off)}). "
                "Set the temperatures again after power on.",
                level=LogLevel.WARNING,
                source="SAFETY",
            )
        return turned_off


_service: Optional[HeaterSafetyService] = None


def get_heater_safety_service() -> HeaterSafetyService:
    global _service
    if _service is None:
        _service = HeaterSafetyService()
    return _service


__all__ = ["HeaterSafetyService", "get_heater_safety_service"]
