"""HAL pin / signal reader for the Visual HAL editor.

The hardware pin set is static while LinuxCNC is running —
components are created at startup and never change — so reading
them through ``hal`` on every request is wasted work. This service
therefore caches the mapped :class:`HalLayoutResponse` after the
first read and returns the cached object forever after
(:meth:`HalPinSignalService.get_layout`).

The actual ``linuxcnc`` / ``hal`` library calls are stubbed for
now: :meth:`_read_pins_from_linuxcnc` and
:meth:`_read_signals_from_linuxcnc` return a hardcoded mock
representation (boolean and float pins) that mirrors what
``hal-pins``/``hal-signals`` introspection would produce. When the
real integration lands, only those two private methods change —
the caching contract and everything above it stays identical.
"""

from __future__ import annotations

import logging
import re
import subprocess
from typing import List, Optional

from dtos.pins.HalPin import HalDirection
from dtos.pins.MachineHalPin import MachineHalPin
from dtos.pins.MachineSignal import MachineHalSignal
from hardware import hal
from mappers.hal_mapper import HalMapper
from models.hal import HalLayoutResponse

logger = logging.getLogger("backend.services.hal_pin_signal")





class HalPinSignalService:
    """Reads (once) and caches the HAL pin/signal layout for the visual editor."""

    def __init__(self) -> None:
        self._layout_cache: Optional[HalLayoutResponse] = None

    def get_layout(self) -> HalLayoutResponse:
        """Return the full editor layout, reading hardware at most once.

        The first call delegates to :meth:`_build_layout`; every
        later call short-circuits on ``self._layout_cache``.
        """
        if self._layout_cache is None:
            self._layout_cache = self._build_layout()
            logger.info(
                "HAL layout cached: %d IN pins, %d OUT pins, %d signals",
                len(self._layout_cache.in_pins),
                len(self._layout_cache.out_pins),
                len(self._layout_cache.signals),
            )
        return self._layout_cache

    def reset_cache(self) -> None:
        """Drop the cached layout (used by tests and future reload flows)."""
        self._layout_cache = None

    # ------------------------------------------------------------------ #
    # Internal assembly                                                   #
    # ------------------------------------------------------------------ #

    def _build_layout(self) -> HalLayoutResponse:
        """Read pins + signals from the (stubbed) HAL and map them.

        The pin set is read exactly once and handed to the signal
        reader so both halves of the layout describe the same pin
        objects (and a layout build costs a single introspection
        pass).
        """
        pins = self._read_pins_from_linuxcnc()
        signals = self._read_signals_from_linuxcnc(pins)
        return HalMapper.to_layout(pins, signals)

    # ------------------------------------------------------------------ #
    # LinuxCNC introspection stubs                                        #
    # ------------------------------------------------------------------ #

    def _read_pins_from_linuxcnc(self) -> List[MachineHalPin]:
        """Reads all pins, types, directions, and values from LinuxCNC via halcmd."""
        pins: List[MachineHalPin] = []

        try:
            raw = subprocess.check_output(
                ["halcmd", "show", "pin"], text=True, stderr=subprocess.DEVNULL
            )
        except (subprocess.SubprocessError, FileNotFoundError):
            return pins

        # Matches lines like:
        # 5  bit   OUT   TRUE  motion.spindle-on
        # 5  float IN    0.0   motion.spindle-speed-in
        pattern = re.compile(
            r"^\s*\d+\s+(?P<type>\w+)\s+(?P<dir>IN|OUT|I/O)\s+(?P<val>\S+)\s+(?P<name>\S+)"
        )

        for line in raw.splitlines():
            m = pattern.match(line)
            if not m:
                continue

            d = m.groupdict()
            full_name = d["name"]
            raw_type = d["type"].lower()
            raw_val = d["val"]

            # Parse value
            if raw_type == "bit":
                val = raw_val.upper() in ("TRUE", "1")
            elif raw_type == "float":
                try:
                    val = float(raw_val)
                except ValueError:
                    val = 0.0
            elif raw_type in ("s32", "u32"):
                try:
                    val = int(raw_val)
                except ValueError:
                    val = 0
            else:
                val = raw_val

            direction = HalDirection.IN if d["dir"] == "IN" else HalDirection.OUT

            parts = full_name.split(".", 1)
            comp_prefix = parts[0] if len(parts) > 1 else "hal"
            short_name = parts[1] if len(parts) > 1 else full_name

            pins.append(
                MachineHalPin(
                    component=comp_prefix,
                    pin=short_name,
                    value=val,
                    direction=direction,
                    description=f"{d['type']} pin ({full_name})"
                )
            )

        return pins

    def _read_signals_from_linuxcnc(
            self, pins: Optional[List[MachineHalPin]] = None
    ) -> List[MachineHalSignal]:
        """Reads all signals and their connected source/target pins."""
        if pins is None:
            pins = self._read_pins_from_linuxcnc()

        # Index pins by full component.pin and short name
        pins_by_key = {}
        for p in pins:
            # Resolve either p.name or p.pin safely
            pin_name = getattr(p, "pin", getattr(p, "name", None))
            comp_name = getattr(p, "component", None)

            if hasattr(p, "get_pin_name"):
                pins_by_key[p.get_pin_name()] = p

            if pin_name:
                pins_by_key[pin_name] = p
                if comp_name:
                    pins_by_key[f"{comp_name}.{pin_name}"] = p

        try:
            raw = subprocess.check_output(
                ["halcmd", "show", "sig"], text=True, stderr=subprocess.DEVNULL
            )
        except (subprocess.SubprocessError, FileNotFoundError):
            return []

        signals: List[MachineHalSignal] = []
        current_sig_name: Optional[str] = None
        source_pin: Optional[MachineHalPin] = None
        target_pins: List[MachineHalPin] = []

        def _flush():
            nonlocal current_sig_name, source_pin, target_pins
            if current_sig_name and (source_pin or target_pins):
                signals.append(
                    MachineHalSignal(
                        name=current_sig_name,
                        source=source_pin,
                        targets=tuple(target_pins),
                        description=f"HAL signal {current_sig_name}",
                    )
                )
            current_sig_name = None
            source_pin = None
            target_pins = []

        # Matches signal header: bit TRUE sig-name
        sig_header = re.compile(r"^\s*(bit|float|s32|u32)\s+\S+\s+(\S+)", re.IGNORECASE)
        # Matches connections: <== comp.pin (source) or ==> comp.pin (target)
        pin_link = re.compile(r"^\s*(<==|==>|<=>)\s+(\S+)")

        for line in raw.splitlines():
            header_m = sig_header.match(line)
            if header_m:
                _flush()
                current_sig_name = header_m.group(2)
                continue

            link_m = pin_link.match(line)
            if link_m and current_sig_name:
                arrow, full_pin_name = link_m.groups()
                short_name = full_pin_name.split(".", 1)[-1]
                matched = pins_by_key.get(full_pin_name) or pins_by_key.get(short_name)

                if matched:
                    if arrow in ("<==", "<=>"):
                        source_pin = matched
                    else:
                        target_pins.append(matched)

        _flush()
        return signals


# Singleton Provider
_SERVICE_INSTANCE = None


def get_hal_pin_signal_service() -> HalPinSignalService:
    global _SERVICE_INSTANCE
    if _SERVICE_INSTANCE is None:
        _SERVICE_INSTANCE = HalPinSignalService()
    return _SERVICE_INSTANCE
