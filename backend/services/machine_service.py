"""Machine service — hardware-layer HAL-pin facade + reminder stubs.

This module is the canonical home for machine-business logic that
does **not** belong to a single backend module:

  * :class:`MachineService` — the hardware-layer HAL-pin facade
    used by anything that needs to read endstop states or dispatch
    G-code against the linuxcnc command channel. The class body
    composes the :class:`DeviceConfigMapper` (``.cfg`` → HAL pin
    names) with the :class:`HalSubscriptionManager` (poll → fire
    callbacks) and the ``execute_gcode`` / ``execute_sync_cmd``
    dispatch helpers so API consumers ask "give me the endstop
    state" without knowing how the pins are wired or how the G-code
    is dispatched.
  * :class:`MachineStubService` — reminder class for the
    not-yet-implemented spindle / heater / fan / extruder surface.
    Methods are ``pass`` bodies today; a follow-up PR will relocate
    each method into its dedicated module (spindle / temperature /
    fan / tools) and delete this class.

The rest of the historical ``MachineControlService`` split along
module boundaries in this round and now lives in:

  * :mod:`modules.state.service` — :class:`StateService` (state /
    mode / MDI / ``MachineState`` enum).
  * :mod:`modules.axis.service` — :class:`AxisService` (homing).
  * :mod:`modules.program.service` — :class:`ProgramService`
    (G-code program lifecycle + ``ProgramProgressResponse``).
  * :mod:`modules.tools.service` — :class:`ToolsService`
    (``collect_tools`` + tool telemetry overlay).
  * :mod:`modules.temperature.service` — :class:`TemperatureService`
    (``collect_sensors`` + ``read_temperature`` helper).
"""
from __future__ import annotations

import logging
from typing import List, Optional

from hardware.connection import (
    DeviceConfigMapper,
    HalSubscriptionManager,
    execute_gcode,
    is_linuxcnc_connected,
)

logger = logging.getLogger("backend.services.machine_service")


class MachineService:
    """Hardware-layer high-level interface (HAL-pin + endstop).

    Composes the :class:`DeviceConfigMapper` (``.cfg`` → HAL pin
    names) with the :class:`HalSubscriptionManager` (poll → fire
    callbacks) and the ``execute_gcode`` / ``execute_sync_cmd``
    dispatch helpers so API consumers ask "give me the endstop
    state" without knowing how the pins are wired or how the G-code
    is dispatched.

    Future entry points (axis home via G-code, tool-change G-code,
    …) extend this class without touching the FastAPI router or
    the lower layers.
    """

    def __init__(self, mapper: DeviceConfigMapper, hal_sub_mgr: HalSubscriptionManager) -> None:
        self.mapper = mapper
        self.hal_mgr = hal_sub_mgr

    def get_endstop_state_subscription(self, pin_list: List[str]) -> dict:
        """Snapshot endstop states + fire the G-code position query.

        Reads every HAL pin via the subscription manager's
        :meth:`HalSubscriptionManager.read_pin` (no subscription is
        registered — this is a one-shot snapshot, not a push
        subscription). When LinuxCNC is reachable the routine
        additionally issues ``M114`` (current position report) so
        the consumer can correlate the pin state with the
        reported axis positions.

        The result is a flat dict suitable for ``JSONResponse`` —
        the router is free to wrap or extend it.
        """
        states = {pin: self.hal_mgr.read_pin(pin) for pin in pin_list}

        gcode_res = self.safe_execute_gcode("M114", 2)

        return {
            "pins": pin_list,
            "states": states,
            "gcode_status": gcode_res,
        }

    def get_endstops(self) -> dict:
        """Top-level call: pins via the mapper, then state read.

        Combines the two Layer-1 / Layer-2 responsibilities:
        :class:`DeviceConfigMapper` knows which pins the machine
        exposes; the subscription manager knows how to read them.
        """
        pins = self.mapper.get_endstop_hal_pin_list()
        return self.get_endstop_state_subscription(pins)

    def safe_execute_gcode(self, command: str, timeout: float = 2.0) -> dict:
        """Executes a G-code command only if the machine is online."""
        if not is_linuxcnc_connected():
            return {"status": "offline"}

        return execute_gcode(command, timeout=timeout)


class MachineStubService:
    """Reminder class for the not-yet-implemented spindle / heater /
    fan / extruder surface.

    Every method is a ``pass`` body. They live here so a follow-up
    PR has a single, obvious hook to relocate each method into its
    dedicated module (``modules.tools``, ``modules.temperature``, …)
    and then delete this class. Until then, importing this class
    surfaces every pending stub method name in one place.
    """



    def get_heater(self):
        pass

    def get_fan(self):
        pass

    def get_extruder(self):
        pass

    def set_heater_temperature(self, heater_temperature: int) -> None:
        pass

    def set_fan_speed(self, fan_speed: int) -> None:
        pass




_machine_service: Optional[MachineService] = None
_machine_stub_service: Optional[MachineStubService] = None


def get_machine_service() -> MachineService:
    """Lazy module-level singleton (HAL-pin facade).

    Mirrors the :class:`backend.hardware.connection._LazyChannel`
    pattern: the instance survives across requests and resets on
    ``uvicorn --reload``. The first call composes a default
    :class:`DeviceConfigMapper` (reads
    ``machine_config/active/hardware.json``) and
    :class:`HalSubscriptionManager`.
    """
    global _machine_service
    if _machine_service is None:
        _machine_service = MachineService(
            mapper=DeviceConfigMapper(),
            hal_sub_mgr=HalSubscriptionManager(),
        )
    return _machine_service


def get_machine_stub_service() -> MachineStubService:
    """Lazy module-level singleton for the reminder stub class."""
    global _machine_stub_service
    if _machine_stub_service is None:
        _machine_stub_service = MachineStubService()
    return _machine_stub_service


__all__ = [
    "MachineService",
    "MachineStubService",
    "get_machine_service",
    "get_machine_stub_service",
]