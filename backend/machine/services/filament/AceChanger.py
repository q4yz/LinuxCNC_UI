"""The ACE's half of a tool change: unwind the old slot, feed the new one
to the toolhead sensor, feed assist on. The motion half (park, cut,
push to the nozzle, purge) is ``ace_change.ngc``.

Lengths get the filament close, the sensors decide (``[ace]``):

* **Unload** — feed assist off, wind ``unload_length`` back, then the
  toolhead sensor (and the hub sensor) must be clear.
* **Load** — the slot must have filament; feed ``bowden_length -
  approach_length`` fast; the hub sensor (if any) must see it; then up to
  twice ``approach_length`` slowly until the toolhead sensor triggers,
  and stop there. Feed assist on: the ACE pushes along while printing.

Every failure is an :class:`AceChangeError` with a message for the
operator; the NGC then pauses and Resume retries.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from core.ace_contract import NO_SLOT, UNKNOWN_SLOT
from models.machineconfig.HardwareJsonModels import Ace

from .ace import AceClient, AceError, AceTimeout, AceUnavailable

logger = logging.getLogger("backend.filament.changer")

#: Extra time over length / speed before a move counts as stuck (s).
MOVE_MARGIN_S = 15.0
#: While approaching the sensor: how often the ACE is asked whether it still feeds (s).
STATUS_EVERY_S = 0.5


class AceChangeError(RuntimeError):
    """A tool change step failed (the message is for the operator)."""


class AceChanger:
    def __init__(
        self,
        client: AceClient,
        config: Ace,
        sensor: Callable[[str], bool | None],
        *,
        poll_s: float = 0.02,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        on_slot: Callable[[int], None] | None = None,
    ) -> None:
        self.client = client
        self.config = config
        self._sensor = sensor
        self._poll_s = poll_s
        self._sleep = sleep
        self._on_slot = on_slot
        self._current = NO_SLOT
        #: What the change is doing now (for the UI), "" when idle.
        self.step = ""

    # -- the loaded slot ---------------------------------------------------- #

    @property
    def current(self) -> int:
        return self._current

    def set_current(self, slot: int) -> None:
        self._current = slot
        if self._on_slot is not None:
            self._on_slot(slot)

    def toolhead_loaded(self) -> bool:
        return self._read(self.config.toolhead_sensor, "toolhead")

    def hub_loaded(self) -> bool | None:
        """``None`` without a hub sensor."""
        return self._read(self.config.hub_sensor, "hub") if self.config.hub_sensor else None

    def _read(self, name: str, what: str) -> bool:
        value = self._sensor(name)
        if value is None:
            raise AceChangeError(f"The {what} filament sensor ({name}) cannot be read")
        return bool(value)

    def reconcile(self) -> int:
        """At start: trust the stored slot only as far as the toolhead sensor
        agrees (filament there but no slot known: unknown; none: unloaded)."""
        try:
            loaded = self.toolhead_loaded()
        except AceChangeError:
            return self._current
        if not loaded:
            self.set_current(NO_SLOT)
        elif self._current == NO_SLOT:
            self.set_current(UNKNOWN_SLOT)
        return self._current

    # -- the change ---------------------------------------------------------- #

    async def change(self, slot: int) -> None:
        """Make ``slot`` the loaded one (``NO_SLOT``: unload only)."""
        if slot == self._current:
            return
        try:
            if self._current >= 0:
                await self.unload(self._current)
            elif self.toolhead_loaded():
                raise AceChangeError(
                    "There is filament at the toolhead but it is not known from which slot: "
                    "pull it out (or set the loaded slot), then Resume")
            else:
                self.set_current(NO_SLOT)
            if slot >= 0:
                await self.load(slot)
        except (AceError, AceTimeout, AceUnavailable) as exc:
            raise AceChangeError(f"ACE: {exc}") from exc
        finally:
            self.step = ""

    async def unload(self, slot: int) -> None:
        cfg = self.config
        self.step = f"unloading T{slot}"
        logger.info("ACE: unload slot %d", slot)
        try:
            await self.client.stop_feed_assist(slot)
        except AceError as exc:  # not assisting: fine
            logger.info("ACE: stop_feed_assist(%d): %s", slot, exc)
        await self.client.unwind(slot, cfg.unload_length, cfg.retract_speed)
        await self.client.wait_ready(cfg.unload_length / cfg.retract_speed + MOVE_MARGIN_S)
        if self.toolhead_loaded():
            raise AceChangeError(f"T{slot} was wound back but the toolhead sensor still sees filament "
                                 "(not cut through, or stuck in the extruder)")
        if self.hub_loaded():
            raise AceChangeError(f"T{slot} was wound back but the hub sensor still sees filament")
        self.set_current(NO_SLOT)

    async def load(self, slot: int) -> None:
        cfg = self.config
        self.step = f"loading T{slot}"
        logger.info("ACE: load slot %d", slot)
        status = await self.client.get_status()
        slots = {s.index: s for s in status.slots}
        if slot not in slots or not slots[slot].has_filament:
            raise AceChangeError(f"T{slot} has no filament")
        fast = cfg.bowden_length - cfg.approach_length
        await self.client.feed(slot, fast, cfg.feed_speed)
        await self.client.wait_ready(fast / cfg.feed_speed + MOVE_MARGIN_S)
        if not self.toolhead_loaded():
            if self.hub_loaded() is False:
                await self._unwind_after_failure(slot, fast)
                raise AceChangeError(f"T{slot}: the filament did not reach the hub sensor")
            if not await self._approach(slot):
                await self._unwind_after_failure(slot, cfg.bowden_length)
                raise AceChangeError(f"T{slot}: the filament did not reach the toolhead sensor")
        await self.client.start_feed_assist(slot)
        self.set_current(slot)

    async def _approach(self, slot: int) -> bool:
        """Feed slowly until the toolhead sensor triggers; stop there. The
        sensor is read every ``poll_s``; the ACE asked every
        :data:`STATUS_EVERY_S` whether the feed already ended short of it."""
        cfg = self.config
        length = min(2 * cfg.approach_length, 2000.0)
        await self.client.feed(slot, length, cfg.approach_speed)
        started = time.monotonic()
        deadline = started + length / cfg.approach_speed + MOVE_MARGIN_S
        next_status = started + STATUS_EVERY_S
        while time.monotonic() < deadline:
            if self.toolhead_loaded():
                await self.client.stop_feed(slot)
                return True
            if time.monotonic() >= next_status:
                next_status = time.monotonic() + STATUS_EVERY_S
                if (await self.client.get_status()).ready:
                    return self.toolhead_loaded()  # the feed ended short of the sensor
            await self._sleep(self._poll_s)
        await self.client.stop_feed(slot)
        return self.toolhead_loaded()

    async def _unwind_after_failure(self, slot: int, length: float) -> None:
        """Pull a half-loaded filament back so the next try starts clean."""
        try:
            await self.client.unwind(slot, length, self.config.retract_speed)
            await self.client.wait_ready(length / self.config.retract_speed + MOVE_MARGIN_S)
        except (AceError, AceTimeout, AceUnavailable) as exc:
            logger.warning("ACE: winding slot %d back after a failed load: %s", slot, exc)


__all__ = ["AceChangeError", "AceChanger"]
