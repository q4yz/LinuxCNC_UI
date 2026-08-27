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
from typing import Optional, List, Dict, Any, Literal

from dtos.axis.AxisDto import AxisStateDTO
from hardware.Connection import execute_sync_cmd, linuxcnc
from mappers.axis.axis_mapper import AxisMapper
from services.HardwareConfigService import HardwareConfigService
from hal_service.jog_service import jog_keepalive, jog_axis, jog_stop

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
        for tool in axes_list:
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


    def home_single_axes(self, axis: str) -> None:
        """Home a single axis by letter, or every axis when ``"all"``.

        The router hands us a canonical letter (``"x"``, ``"y"``,
        ``"z"``) or the ``"all"`` keyword. ``"all"`` fans out to
        :meth:`home_all_axes` so the historic ``home -1`` dispatch
        keeps working; the letter branches own the
        ``AxisState -> joint_numbers -> stepgen channel`` mapping
        the operator-facing payload needs.
        """
        if axis == "all":
            self.home_all_axes()
            return

        # Clean lookup: find the specific axis DTO without a manual loop
        target_axis = next((a for a in self.get_axis() if a.id == axis), None)

        if target_axis is None:
            raise ValueError(f"Cannot home unknown axis: {axis!r}")

        execute_sync_cmd("mode", 1.0, getattr(linuxcnc, "MODE_MANUAL", 1))
        execute_sync_cmd("teleop_enable", 1.0, 0)
        # Coupled axes synchronize automatically via HOME_SEQUENCE
        execute_sync_cmd("home", 3.0, target_axis.joint_numbers[0])

    def update_settings(self, multiplier: float, absolute_speed_limit: int) -> None:
        execute_sync_cmd("feedrate", 0, float(multiplier))
        execute_sync_cmd("maxvel", 0, float(absolute_speed_limit) / 60.0)

    async def dispatch_inbound(self, msg: Dict[str, Any]) -> bool:
        """
        Route an inbound axis-related JSON command.

        Args:
            msg (dict): The parsed JSON payload from the WebSocket.

        Returns:
            bool: True if the message type was recognized and handled, False otherwise.
        """
        mtype = msg.get("type")

        if mtype == "jog_keepalive":
            axes = msg.get("axes") or []
            if not isinstance(axes, list):
                logger.warning("jog_keepalive: 'axes' must be a list, got %r", type(axes))
                return True

            jog_keepalive([int(a) for a in axes])
            return True

        if mtype == "jog_axis":
            velocities = msg.get("velocities") or {}
            if not isinstance(velocities, dict):
                logger.warning("jog_axis: 'velocities' must be a dict, got %r", type(velocities))
                return True

            distance = float(msg.get("distance") or 0)
            coerced = {}
            for axis, velocity in velocities.items():
                try:
                    coerced[int(axis)] = float(velocity)
                except (TypeError, ValueError):
                    logger.warning("jog_axis: dropping bad axis/velocity pair %r=%r", axis, velocity)

            jog_axis(coerced, distance)
            return True

        if mtype == "jog_stop":
            axes = msg.get("axes") or []
            if not isinstance(axes, list):
                logger.warning("jog_stop: 'axes' must be a list, got %r", type(axes))
                return True

            jog_stop([int(a) for a in axes])
            return True

        # Not an axis command
        return False


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