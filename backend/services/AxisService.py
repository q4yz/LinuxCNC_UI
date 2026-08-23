"""Axis module service — :class:`AxisService` (homing facade).

This is the canonical home for the home-axis dispatch that used to
live on ``backend.services.machine_service.MachineControlService``.
The HTTP edge (``backend/modules/axis/router.py``) is a thin
wrapper around :func:`get_axis_service`; this module owns the
``MODE_MANUAL`` pre-switch and the per-axis ``home`` dispatch.

The facade stays whole — the HTTP routing was split, but the
business logic does not need to follow that split.
"""
from __future__ import annotations

import logging
from typing import Optional, List

from dtos.axis.axis_dtos import AxisStateDTO
from hardware.Connection import execute_sync_cmd, linuxcnc
from mappers.axis.axis_mapper import AxisMapper
from services.HardwareConfigService import HardwareConfigService

logger = logging.getLogger("backend.services.AxisService")


class AxisService:
    """Axis-motion facade (homing).

    The ``MODE_MANUAL`` pre-switch is the only behavioural difference
    from a naive ``execute_sync_cmd("home", 3, axis)`` — a stale
    ``MODE_AUTO`` silently swallows the home command otherwise.
    ``axis == -1`` triggers a sweep across the canonical three
    Cartesian axes (X, Y, Z); a non-``-1`` value homes a single
    axis.
    """
    def __init__(self) -> None:
        self._state_cache = None

    def preload_hal_pins(self) -> None:
        """
        Forces the factory to build the DTOs.
        This queues the pins in HalPin._pending_pins.
        Must be called at startup BEFORE HalPin.initialize_component()
        """

        if self._state_cache is not None:
            return

        config_service = HardwareConfigService()
        axes_list = config_service.get_axes()



        out = []
        for tool in axes_list:  # Assuming get_tools() reads your JSON config
            out.append(AxisMapper.from_dict_to_dto(tool))

        self._state_cache = out
        logging.info("Preloaded %d axes.", len(out))


    def get_axis(self) -> List[AxisStateDTO]:

        if self._state_cache is None:
            self.preload_hal_pins()

        return self._state_cache



    def home_all_axes(self) -> None:
        """Home all axes according to the INI file's HOME_SEQUENCE.

        Always switches to MODE_MANUAL first to ensure the command
        is accepted by LinuxCNC, mirroring the behavior of the AXIS GUI.
        """
        execute_sync_cmd("mode", 1, getattr(linuxcnc, "MODE_MANUAL", 1))
        execute_sync_cmd("teleop_enable", 1.0, 0)
        execute_sync_cmd("home", 3, -1)


    def home_single_axes(self, axis: int) -> None:
        if axis == -1:
            self.home_all_axes()
            return

        execute_sync_cmd("mode", 1, getattr(linuxcnc, "MODE_MANUAL", 1))
        execute_sync_cmd("teleop_enable", 1.0, 0)
        execute_sync_cmd("home", 3, axis)


_axis_service: Optional[AxisService] = None


def get_axis_service() -> AxisService:
    """Lazy module-level singleton (homing facade).

    Mirrors the historical :func:`backend.services.machine_service.get_machine_control_service`
    pattern. The instance survives across requests and resets on
    ``uvicorn --reload``.
    """
    global _axis_service
    if _axis_service is None:
        _axis_service = AxisService()
    return _axis_service


__all__ = [
    "AxisService",
    "get_axis_service",
]