"""An ADXL345 accelerometer for resonance tests (``ResonanceService``): on
the host's SPI (BTT CB1, Raspberry Pi), read from its FIFO (:class:`Adxl345`),
or on a CAN node, recorded in HAL (:class:`NodeAdxl345`).

Wiring: the chip's SDO / SDA / SCL / CS to the host's MISO / MOSI / SCLK and
a chip select of a spidev device (``[adxl345] spi_device: /dev/spidev1.1``),
VCC 3.3 V, GND. Needs the ``spidev`` Python module (``python3-spidev``).
"""
from __future__ import annotations

from models.machineconfig.HardwareJsonModels import Adxl345 as Adxl345Settings

import queue
import re
import shutil
import subprocess
import threading
import time
from typing import Any, Callable, List, Optional, Tuple

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
    def __init__(self, config: Adxl345Settings) -> None:
        self._config = config
        self._spi: Any = None
        self._axes = parse_axes_map(config.axes_map)
        self.rate = config.rate
        if self.rate not in RATE_CODES:
            raise Adxl345Error(f"rate {self.rate}: one of {sorted(RATE_CODES)}")

    def open(self) -> None:
        try:
            import spidev
        except ImportError as exc:
            raise Adxl345Error("the spidev Python module is missing (apt install python3-spidev)") from exc
        device = self._config.spi_device
        match = re.fullmatch(r"/dev/spidev(\d+)\.(\d+)", device)
        if not match:
            raise Adxl345Error(f"spi_device {device!r}: /dev/spidev<bus>.<cs>")
        spi = spidev.SpiDev()
        try:
            spi.open(int(match.group(1)), int(match.group(2)))
        except OSError as exc:
            raise Adxl345Error(f"cannot open {device}: {exc}") from exc
        spi.mode = 3
        spi.max_speed_hz = self._config.spi_speed
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


class NodeAdxl345:
    """The ADXL345 of a CAN node (``[adxl345] cs_pin: <node>:PB12``): the
    node firmware reads it, the hub writes X / Y (mm/s², axes mapped) into
    two process variables, a HAL ``sampler`` records them every servo
    period (`Adxl345HalMapper`) and ``halsampler`` hands them over here.
    Same interface as :class:`Adxl345`; no Z (the frame's PVs are few)."""

    #: ``sampler.0.enable``, netted in webgui_connections.hal.
    RECORD_PIN = "accel-record"

    def __init__(self, config: Adxl345Settings, record: Callable[[bool], None],
                 period_s: Optional[float] = None) -> None:
        self._config = config
        self._record = record
        self.period = period_s or servo_period_s()
        self.rate = 1.0 / self.period
        self._proc: Any = None
        self._queue: "queue.Queue[Tuple[int, float, float]]" = queue.Queue()
        self._reader: Optional[threading.Thread] = None
        self._first_tag: Optional[int] = None
        self._start = 0.0

    def open(self) -> None:
        if shutil.which("halsampler") is None:
            raise Adxl345Error("halsampler is missing (LinuxCNC's HAL tools): the node accelerometer needs it")
        self._record(False)
        try:
            self._proc = subprocess.Popen(["halsampler", "-c", "0", "-t"], stdout=subprocess.PIPE,
                                          stderr=subprocess.DEVNULL, text=True, bufsize=1)
        except OSError as exc:
            raise Adxl345Error(f"cannot start halsampler: {exc}") from exc
        self._reader = threading.Thread(target=self._read_lines, name="halsampler", daemon=True)
        self._reader.start()
        time.sleep(0.1)  # what an earlier test left in the FIFO
        self._drain()
        self._first_tag = None
        self._start = time.monotonic()
        self._record(True)

    def _read_lines(self) -> None:
        stdout = self._proc.stdout if self._proc is not None else None
        if stdout is None:
            return
        for line in stdout:
            parsed = parse_sampler_line(line)
            if parsed is not None:
                self._queue.put(parsed)

    def _drain(self) -> List[Tuple[int, float, float]]:
        items = []
        while True:
            try:
                items.append(self._queue.get_nowait())
            except queue.Empty:
                return items

    def close(self) -> None:
        self._record(False)
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None

    def read_fifo(self) -> List[Sample]:
        """The samples recorded since the last call, timed by the servo
        period from the first one (the sampler's own spacing)."""
        samples: List[Sample] = []
        for tag, x, y in self._drain():
            if self._first_tag is None:
                self._first_tag = tag
            samples.append((self._start + (tag - self._first_tag) * self.period, x, y, 0.0))
        return samples


def parse_sampler_line(line: str) -> Optional[Tuple[int, float, float]]:
    """``halsampler -t`` output: ``<sample number> <x> <y>``."""
    parts = line.split()
    if len(parts) < 3:
        return None
    try:
        return int(parts[0]), float(parts[1]), float(parts[2])
    except ValueError:
        return None


def servo_period_s() -> float:
    """LinuxCNC's ``[EMCMOT] SERVO_PERIOD`` (ns) of the running machine,
    1 ms when it cannot be read."""
    try:
        import linuxcnc

        stat = linuxcnc.stat()
        stat.poll()
        value = linuxcnc.ini(stat.ini_filename).find("EMCMOT", "SERVO_PERIOD")
        if value:
            return float(value) * 1e-9
    except Exception:  # noqa: BLE001 - no LinuxCNC: the usual period
        pass
    return 0.001


def is_node(config: Adxl345Settings) -> bool:
    """On a CAN node (``cs_pin``), not the host's SPI."""
    return bool(config.cs_pin)


__all__ = ["Adxl345", "Adxl345Error", "NodeAdxl345", "Sample", "decode", "is_node", "parse_axes_map",
           "parse_sampler_line", "servo_period_s"]
