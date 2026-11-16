"""An ADXL345 accelerometer on the host's SPI (BTT CB1, Raspberry Pi), read
from its FIFO — for resonance tests (``ResonanceService``).

Wiring: the chip's SDO / SDA / SCL / CS to the host's MISO / MOSI / SCLK and
a chip select of a spidev device (``[adxl345] spi_device: /dev/spidev1.1``),
VCC 3.3 V, GND. Needs the ``spidev`` Python module (``python3-spidev``).
"""
from __future__ import annotations

import re
import time
from typing import Any, List, Tuple

DEVID = 0x00
BW_RATE = 0x2C
POWER_CTL = 0x2D
DATA_FORMAT = 0x31
DATAX0 = 0x32
FIFO_CTL = 0x38
FIFO_STATUS = 0x39
DEVID_ADXL345 = 0xE5
#: Output data rate -> BW_RATE code.
RATE_CODES = {3200: 0x0F, 1600: 0x0E, 800: 0x0D, 400: 0x0C}
#: Full resolution: 3.9 mg per LSB, in mm/s².
SCALE_MM_S2 = 0.0039 * 9806.65

Sample = Tuple[float, float, float, float]  # time, x, y, z (mm/s², machine axes)


class Adxl345Error(RuntimeError):
    """The chip cannot be reached / read."""


def parse_axes_map(axes_map: str) -> List[Tuple[int, float]]:
    """``"-y,x,z"`` -> for each machine axis (x, y, z): (chip axis index, sign)."""
    result = []
    for part in axes_map.replace(" ", "").lower().split(","):
        sign = -1.0 if part.startswith("-") else 1.0
        result.append(("xyz".index(part.lstrip("-")), sign))
    return result


def decode(raw: List[int], axes: List[Tuple[int, float]]) -> Tuple[float, float, float]:
    """Six data bytes (little-endian x, y, z) -> machine-axis mm/s²."""
    chip = []
    for k in range(3):
        value = raw[2 * k] | (raw[2 * k + 1] << 8)
        if value & 0x8000:
            value -= 0x10000
        chip.append(value * SCALE_MM_S2)
    return tuple(chip[index] * sign for index, sign in axes)


class Adxl345:
    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config
        self._spi: Any = None
        self._axes = parse_axes_map(str(config.get("axes_map") or "x,y,z"))
        self.rate = int(config.get("rate") or 3200)
        if self.rate not in RATE_CODES:
            raise Adxl345Error(f"rate {self.rate}: one of {sorted(RATE_CODES)}")

    def open(self) -> None:
        try:
            import spidev
        except ImportError as exc:
            raise Adxl345Error("the spidev Python module is missing (apt install python3-spidev)") from exc
        device = str(self._config.get("spi_device") or "/dev/spidev1.1")
        match = re.fullmatch(r"/dev/spidev(\d+)\.(\d+)", device)
        if not match:
            raise Adxl345Error(f"spi_device {device!r}: /dev/spidev<bus>.<cs>")
        spi = spidev.SpiDev()
        try:
            spi.open(int(match.group(1)), int(match.group(2)))
        except OSError as exc:
            raise Adxl345Error(f"cannot open {device}: {exc}") from exc
        spi.mode = 3
        spi.max_speed_hz = int(self._config.get("spi_speed") or 5_000_000)
        self._spi = spi
        devid = self._read(DEVID, 1)[0]
        if devid != DEVID_ADXL345:
            self.close()
            raise Adxl345Error(f"no ADXL345 on {device} (device id 0x{devid:02x}, expected 0xe5) — check the wiring")
        self._write(POWER_CTL, 0x00)
        self._write(DATA_FORMAT, 0x0B)          # full resolution, ±16 g
        self._write(BW_RATE, RATE_CODES[self.rate])
        self._write(FIFO_CTL, 0x80)             # stream mode
        self._write(POWER_CTL, 0x08)            # measure

    def close(self) -> None:
        if self._spi is not None:
            try:
                self._write(POWER_CTL, 0x00)
                self._spi.close()
            except OSError:
                pass
            self._spi = None

    def _read(self, register: int, count: int) -> List[int]:
        command = register | 0x80 | (0x40 if count > 1 else 0)
        return list(self._spi.xfer2([command] + [0] * count)[1:])

    def _write(self, register: int, value: int) -> None:
        self._spi.xfer2([register & 0x3F, value & 0xFF])

    def read_fifo(self) -> List[Sample]:
        """Every sample in the FIFO now, timed back from now at the rate."""
        entries = self._read(FIFO_STATUS, 1)[0] & 0x3F
        now = time.monotonic()
        samples: List[Sample] = []
        for k in range(entries):
            x, y, z = decode(self._read(DATAX0, 6), self._axes)
            samples.append((now - (entries - 1 - k) / self.rate, x, y, z))
        return samples


__all__ = ["Adxl345", "Adxl345Error", "Sample", "decode", "parse_axes_map"]
