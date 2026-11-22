"""The lifecycle every service with ``webgui.*`` HAL pins follows.

LinuxCNC's ``hal`` module creates a userspace component's pins only
before ``ready()``: so first every service queues its pins
(:meth:`HalPinService.preload_hal_pins`), then the ``webgui`` component
is locked (``HalPin.initialize_component``), then every service writes
its start values (:meth:`HalPinService.apply_initial`) — a write before
the component exists is lost. ``main.setup_hal_pins`` runs the three
steps over :func:`services.HalPinServices.hal_pin_services`.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class HalPinService(ABC):
    @abstractmethod
    def preload_hal_pins(self) -> None:
        """Queue this service's pins (create the ``HalPin`` objects). No writes."""

    def apply_initial(self) -> None:
        """Write the start values (after ``HalPin.initialize_component``). Default: none."""


__all__ = ["HalPinService"]
