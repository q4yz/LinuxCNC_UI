"""The ACE Pro in the machine backend (``[ace]``): the link, the tool
change hand-over, manual moves, the dryer.

* **Hand-over** (``core.ace_contract``): ``ace_change.ngc`` raises
  ``webgui.ace-request`` with the slot on ``webgui.ace-slot``; this runs
  :class:`AceChanger` and answers with ``webgui.ace-done`` (and
  ``webgui.ace-error`` when it failed), cleared when the request drops.
  ``webgui.ace-current`` is the loaded slot (-1 none, -2 unknown), kept
  across restarts (``backend/data/ace_state.json``) as far as the toolhead
  sensor agrees.
* **Sensors**: the ``[input_pin]``s ``[ace]`` names, read through
  :class:`services.io.IoService` (``webgui.<name>``).
* **Without hardware** (no HAL, or ``LINUXCNC_UI_ACE_SIM=1``): a simulated
  ACE, whose filament path also drives the sensors.
* **Commands**: a tool change is ``M640 P<slot>`` (from the UI it goes
  through MDI, so the motion half runs too); console: ``T<n>`` /
  ``ACE_CHANGE_TOOL TOOL=<n>`` (-> ``M640``), ``ACE_FEED`` / ``ACE_RETRACT
  INDEX= LENGTH= SPEED=``, ``ACE_START_DRYING TEMP= DURATION=``,
  ``ACE_STOP_DRYING``.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core import ace_contract as contract
from core.atomic_json import atomic_write_json
from core.secret_file import DATA_DIR
from exceptions import BadRequestError, ConflictError, ServiceUnavailableError
from models.AceModels import AceDryerResponse, AceSlotResponse, AceStateResponse
from models.machineconfig.HardwareJsonModels import Ace
from services.HalPinService import HalPinService

from .ace import AceClient, AceError, AceTimeout, AceUnavailable
from .ace.transport import AceTransport
from .AceChanger import AceChangeError, AceChanger

logger = logging.getLogger("backend.filament.ace_service")

SIM_ENV = "LINUXCNC_UI_ACE_SIM"
STATE_ENV = "LINUXCNC_UI_ACE_STATE"
DEFAULT_STATE_FILE = DATA_DIR / "ace_state.json"
POLL_S = 0.05
_PARAM = re.compile(r"([A-Za-z_]+)\s*=\s*([-+]?(?:\d+\.?\d*|\.\d+))")
_TOOL = re.compile(r"^\s*T\s*(\d+)\s*$", re.IGNORECASE)


@dataclass
class AcePins:
    request: Any
    slot: Any
    done: Any
    error: Any
    current: Any


class AceService(HalPinService):
    def __init__(
        self,
        *,
        transport_factory: Callable[[Ace], AceTransport] | None = None,
        sensor: Callable[[str], bool | None] | None = None,
        pins: AcePins | None = None,
        config: Ace | None = None,
        state_file: Path | None = None,
        poll_s: float = POLL_S,
    ) -> None:
        self.config = config
        self._pins = pins
        self._transport_factory = transport_factory
        self._sensor = sensor
        self._state_file = Path(state_file or os.environ.get(STATE_ENV) or DEFAULT_STATE_FILE)
        self._poll_s = poll_s
        self.client: AceClient | None = None
        self.changer: AceChanger | None = None
        self._sim: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._watch: asyncio.Task[None] | None = None
        self._job: asyncio.Task[None] | None = None
        self.last_error = ""

    # -- HAL --------------------------------------------------------------- #

    def preload_hal_pins(self) -> None:
        if self.config is None:
            from models.machineconfig.HardwareRecords import HardwareRecords
            from services.machine.HardwareConfigService import HardwareConfigService

            self.config = HardwareRecords.ace(HardwareConfigService().load_payload())
        if self.config is None or self._pins is not None:
            return
        from dtos.pins.HalPin import HalDataType
        from dtos.pins.ReadOnlyDynamicHalPin import ReadOnlyDynamicHalPin
        from dtos.pins.ReadWriteDynamicHalPin import ReadWriteDynamicHalPin

        self._pins = AcePins(
            request=ReadOnlyDynamicHalPin(contract.PIN_REQUEST, HalDataType.BIT, "ACE: the tool change asks (M640)"),
            slot=ReadOnlyDynamicHalPin(contract.PIN_SLOT, HalDataType.FLOAT, "ACE: the slot to load (-1 unload)"),
            done=ReadWriteDynamicHalPin(contract.PIN_DONE, HalDataType.BIT, "ACE: the hand-over finished"),
            error=ReadWriteDynamicHalPin(contract.PIN_ERROR, HalDataType.BIT, "ACE: ... and failed"),
            current=ReadWriteDynamicHalPin(contract.PIN_CURRENT, HalDataType.FLOAT,
                                           "ACE: the loaded slot (-1 none, -2 unknown)"),
        )

    def apply_initial(self) -> None:
        if self._pins is None:
            return
        self._write(self._pins.done, False)
        self._write(self._pins.error, False)
        self._write(self._pins.current, float(self._stored_slot()))

    @staticmethod
    def _write(pin: Any, value: Any) -> None:
        try:
            pin.set_value(value)
        except Exception as exc:  # noqa: BLE001 - a missing HAL must not stop the backend
            logger.warning("ACE: HAL write failed: %s", exc)

    @staticmethod
    def _read(pin: Any) -> Any:
        try:
            return pin.get_value()
        except Exception:  # noqa: BLE001
            return None

    # -- lifecycle ------------------------------------------------------- #

    @property
    def configured(self) -> bool:
        return self.config is not None

    async def start(self) -> None:
        if self.config is None or self.client is not None:
            return
        self._loop = asyncio.get_running_loop()
        transport = self._make_transport(self.config)
        self.client = AceClient(transport, on_connection=self._on_connection)
        self.changer = AceChanger(self.client, self.config, self._sensor or self._default_sensor,
                                  on_slot=self._on_slot)
        self.changer.set_current(self._stored_slot())
        self.client.start()
        self._watch = self._loop.create_task(self._watch_loop(), name="ace-handshake")
        logger.info("ACE: started (%s)", "simulated" if self._sim is not None else self.config.serial)

    async def stop(self) -> None:
        for task in (self._watch, self._job):
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        self._watch = self._job = None
        if self.client is not None:
            await self.client.stop()
        self.client = None

    def _make_transport(self, config: Ace) -> AceTransport:
        if self._transport_factory is not None:
            return self._transport_factory(config)
        from hardware import HAS_HAL

        if os.environ.get(SIM_ENV, "").lower() in ("1", "true", "yes") or not HAS_HAL:
            from .ace.sim import SimulatedAce

            self._sim = SimulatedAce()
            return self._sim
        from .ace.transport import SerialTransport

        return SerialTransport(config.serial)

    def _default_sensor(self, name: str) -> bool | None:
        if self._sim is not None and self.config is not None:
            # the simulated filament path: toolhead at the bowden end, hub 50 mm out
            if name == self.config.toolhead_sensor:
                return bool(self._sim.filament_at(self.config.bowden_length))
            if name == self.config.hub_sensor:
                return bool(self._sim.filament_at(50.0))
        from services.io.IoService import get_io_service

        return get_io_service().input_value(name)

    def _on_connection(self, connected: bool) -> None:
        if connected:
            self.last_error = ""
            if self.changer is not None:
                self.changer.reconcile()
        elif self.client is not None:
            self.last_error = f"ACE not connected: {self.client.last_error or 'no link'}"

    # -- the loaded slot --------------------------------------------------- #

    def _stored_slot(self) -> int:
        try:
            value = int(json.loads(self._state_file.read_text(encoding="utf-8")).get("current_slot", contract.NO_SLOT))
        except (OSError, ValueError, AttributeError):
            return contract.NO_SLOT
        return value if value in (contract.NO_SLOT, contract.UNKNOWN_SLOT, 0, 1, 2, 3) else contract.NO_SLOT

    def _on_slot(self, slot: int) -> None:
        if self._pins is not None:
            self._write(self._pins.current, float(slot))
        try:
            atomic_write_json(self._state_file, {"current_slot": slot})
        except OSError as exc:
            logger.warning("ACE: could not store the loaded slot: %s", exc)

    # -- the hand-over ----------------------------------------------------- #

    async def _watch_loop(self) -> None:
        was_requested = False
        while True:
            await asyncio.sleep(self._poll_s)
            if self._pins is None:
                continue
            requested = bool(self._read(self._pins.request))
            if requested and not was_requested and (self._job is None or self._job.done()):
                slot_value = self._read(self._pins.slot)
                slot = round(float(slot_value)) if slot_value is not None else contract.NO_SLOT
                self._job = asyncio.get_running_loop().create_task(self._serve(slot), name="ace-change")
            elif not requested and was_requested:
                self._write(self._pins.done, False)
                self._write(self._pins.error, False)
            was_requested = requested

    async def _serve(self, slot: int) -> None:
        """Run one change for the NGC and answer it."""
        assert self.changer is not None and self._pins is not None
        failed = False
        try:
            if not 0 <= slot <= 3 and slot != contract.NO_SLOT:
                raise AceChangeError(f"M640 P{slot}: the slot is 0-3 (or -1 to unload)")
            await self.changer.change(slot)
            self.last_error = ""
        except AceChangeError as exc:
            failed = True
            self.last_error = str(exc)
            self._console(f"ACE: {exc}", error=True)
        except Exception as exc:
            failed = True
            self.last_error = f"ACE: unexpected error: {exc}"
            logger.exception("ACE change failed")
            self._console(self.last_error, error=True)
        self._write(self._pins.error, failed)
        self._write(self._pins.done, True)

    @staticmethod
    def _console(text: str, error: bool = False) -> None:
        try:
            from services.machine.ConsoleLogger import LogLevel, get_console_logger

            get_console_logger().log_event(text, level=LogLevel.ERROR if error else LogLevel.INFO, source="ACE")
        except Exception:  # noqa: BLE001 - logging must not break the change
            logger.info(text)

    # -- state ------------------------------------------------------------ #

    @property
    def changing(self) -> bool:
        return self._job is not None and not self._job.done()

    def state(self) -> AceStateResponse:
        if self.config is None:
            return AceStateResponse(configured=False)
        client, changer = self.client, self.changer
        status = client.status if client is not None else None
        info = client.info if client is not None else None

        def sensor(name: str | None) -> bool | None:
            if not name or changer is None:
                return None
            try:
                return (self._sensor or self._default_sensor)(name)
            except Exception:  # noqa: BLE001
                return None

        return AceStateResponse(
            configured=True,
            connected=bool(client is not None and client.connected),
            model=info.model if info else "",
            firmware=info.firmware if info else "",
            status=status.status if status else "",
            action=status.action if status else "",
            temp=status.temp if status else None,
            slots=[AceSlotResponse(index=s.index, status=s.status, type=s.type, brand=s.brand, sku=s.sku,
                                   color=list(s.color) if s.color else None, rfid=s.rfid)
                   for s in (status.slots if status else ())],
            dryer=(AceDryerResponse(drying=status.dryer.drying, target_temp=status.dryer.target_temp,
                                    remain_min=status.dryer.remain_min, duration_min=status.dryer.duration_min)
                   if status else None),
            current_slot=changer.current if changer is not None else self._stored_slot(),
            changing=self.changing,
            step=changer.step if changer is not None else "",
            toolhead_sensor=sensor(self.config.toolhead_sensor),
            hub_sensor=sensor(self.config.hub_sensor),
            last_error=self.last_error,
        )

    # -- commands (REST / console) ------------------------------------------- #

    def _ready_client(self) -> AceClient:
        if self.config is None:
            raise ConflictError("This machine has no [ace] in its profile.")
        if self.client is None or not self.client.connected:
            raise ServiceUnavailableError(f"The ACE is not connected ({self.last_error or 'no link'}).")
        if self.changing:
            raise ConflictError("A tool change is running.")
        return self.client

    async def _call(self, action: Any) -> None:
        try:
            await action
            if self.client is not None:
                await self.client.get_status()  # the answer shows the effect
        except ValueError as exc:
            raise BadRequestError(str(exc)) from None
        except (AceError, AceTimeout, AceUnavailable) as exc:
            raise ServiceUnavailableError(f"ACE: {exc}") from None

    async def feed(self, index: int, length: float, speed: float) -> None:
        await self._call(self._ready_client().feed(index, length, speed))

    async def unwind(self, index: int, length: float, speed: float) -> None:
        await self._call(self._ready_client().unwind(index, length, speed))

    async def start_drying(self, temp: float, minutes: int) -> None:
        await self._call(self._ready_client().start_drying(temp, minutes))

    async def stop_drying(self) -> None:
        await self._call(self._ready_client().stop_drying())

    def set_current(self, slot: int) -> None:
        """The operator says which slot is really loaded (after handling it by hand)."""
        if self.config is None or self.changer is None:
            raise ConflictError("This machine has no [ace] in its profile.")
        if self.changing:
            raise ConflictError("A tool change is running.")
        self.changer.set_current(slot)
        self.last_error = ""

    def translate_mdi(self, command: str) -> str:
        """``T<n>`` / ``ACE_CHANGE_TOOL TOOL=<n>`` typed in MDI -> ``M640 P<n>``."""
        if self.config is None:
            return command
        match = _TOOL.match(command)
        if match is None and command.strip().upper().startswith("ACE_CHANGE_TOOL"):
            match = re.search(r"TOOL\s*=\s*(-?\d+)", command, re.IGNORECASE)
        return f"{contract.M_CODE} P{int(match.group(1))}" if match else command

    def run_command(self, command: str) -> bool:
        """``ACE_FEED`` / ``ACE_RETRACT`` / ``ACE_START_DRYING`` / ``ACE_STOP_DRYING``
        typed in the console (from a worker thread): ``True`` when it was one."""
        upper = command.strip().upper()
        if not upper.startswith("ACE_") or upper.startswith("ACE_CHANGE_TOOL"):
            return False
        params = {k.upper(): float(v) for k, v in _PARAM.findall(command)}
        word = upper.split()[0]
        if word in ("ACE_FEED", "ACE_RETRACT"):
            index, length = int(params.get("INDEX", -1)), params.get("LENGTH")
            if length is None:
                raise BadRequestError(f"{word} INDEX=<0-3> LENGTH=<mm> [SPEED=<mm/s>]")
            speed = params.get("SPEED", 25.0)
            coro = self.feed(index, length, speed) if word == "ACE_FEED" else self.unwind(index, length, speed)
            text = f"{'Feeding' if word == 'ACE_FEED' else 'Winding back'} slot {index + 1}: {length:g} mm"
        elif word == "ACE_START_DRYING":
            if "TEMP" not in params or "DURATION" not in params:
                raise BadRequestError("ACE_START_DRYING TEMP=<°C> DURATION=<min>")
            coro = self.start_drying(params["TEMP"], int(params["DURATION"]))
            text = f"Drying at {params['TEMP']:g} °C for {int(params['DURATION'])} min"
        elif word == "ACE_STOP_DRYING":
            coro, text = self.stop_drying(), "Drying stopped"
        else:
            raise BadRequestError(f"Unknown ACE command {word}")
        self._run_from_thread(coro)
        self._console(text)
        return True

    def _run_from_thread(self, coro: Any) -> None:
        if self._loop is None:
            coro.close()
            raise ConflictError("This machine has no [ace] in its profile.")
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self._loop:  # on the loop already: do not block it
            self._loop.create_task(coro)
            return
        asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout=10)


_service: AceService | None = None


def get_ace_service() -> AceService:
    global _service
    if _service is None:
        _service = AceService()
    return _service


__all__ = ["AcePins", "AceService", "get_ace_service"]
