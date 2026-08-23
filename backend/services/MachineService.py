"""Machine Command Service — hardware-layer G-code and MDI facade.

This module provides the central :class:`MachineService` used by
higher-level modules (SpindleDigital, Axes, Program, etc.) to dispatch
commands to the LinuxCNC hardware layer.

By routing all execution through this service, API consumers can
ask to "ensure MDI mode" or "dispatch this M-code" without needing
to know the low-level sync mechanics or linuxcnc channel specifics.
"""
from __future__ import annotations

import logging
from typing import Optional

from hardware.connection import (
    DeviceConfigMapper,
    HalSubscriptionManager,
    execute_gcode,
    execute_sync_cmd,
    is_linuxcnc_connected, ensure_mdi_mode,
)



logger = logging.getLogger("backend.services.machine_service")


class MachineService:
    """Hardware-layer high-level interface for command dispatch.

    Provides handy, safe wrappers for executing G-code, managing
    machine modes (like MDI), and directly interacting with the
    LinuxCNC command channel.
    """

    def __init__(self, mapper: DeviceConfigMapper, hal_sub_mgr: HalSubscriptionManager) -> None:
        self.mapper = mapper
        self.hal_mgr = hal_sub_mgr

    def safe_execute_gcode(self, command: str, timeout: float = 2.0) -> dict:
        """Executes a G-code command only if the machine is online."""
        if not is_linuxcnc_connected():
            logger.warning("Dropped G-code dispatch (offline): %s", command)
            return {"status": "offline"}

        return execute_gcode(command, timeout=timeout)

    def ensure_mdi_mode(self) -> None:
        """Switch the task into MDI mode and wait for the change to commit."""
        ensure_mdi_mode()     # <--- Call the imported function

    def dispatch_mdi(self, command: str) -> None:
        """Issue a single MDI command without waiting for completion."""
        logger.info("MDI Dispatch -> %s", command)
        execute_sync_cmd("mdi", 0, command)




_machine_service: Optional[MachineService] = None


def get_machine_service() -> MachineService:
    """Lazy module-level singleton (Command execution facade).

    Mirrors the :class:`backend.hardware.connection._LazyChannel`
    pattern: the instance survives across requests and resets on
    ``uvicorn --reload``. The first call composes a default
    :class:`DeviceConfigMapper` and :class:`HalSubscriptionManager`.
    """
    global _machine_service
    if _machine_service is None:
        _machine_service = MachineService(
            mapper=DeviceConfigMapper(),
            hal_sub_mgr=HalSubscriptionManager(),
        )
    return _machine_service


__all__ = [
    "MachineService",
    "get_machine_service",
]