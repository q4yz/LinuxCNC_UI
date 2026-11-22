"""The HAL pins of the calibration services: input shaper / skew /
resonance test (``ShaperService``), the PID relay (``PidCalibrateService``)
and a CAN node accelerometer's recording (``ResonanceService``). Their
state reaches the UI through the calibration catalog."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from dtos.pins.HalPin import HalPin


@dataclass(frozen=True, slots=True)
class ShaperPins:
    """The jointshape inputs, ``webgui.<name>`` (``webgui_connections.hal``)."""
    shaper_freq_x: HalPin[float]
    shaper_freq_y: HalPin[float]
    skew_xy: HalPin[float]
    resonance_amp_x: HalPin[float]
    resonance_amp_y: HalPin[float]
    resonance_freq: HalPin[float]

    def shaper_freq(self, axis: str) -> HalPin[float]:
        return self.shaper_freq_x if axis == "x" else self.shaper_freq_y

    def resonance_amp(self, axis: str) -> HalPin[float]:
        return self.resonance_amp_x if axis == "x" else self.resonance_amp_y


@dataclass(frozen=True, slots=True)
class PidTunePins:
    """One heater's ``webgui.tune-<id>-enable`` / ``-duty`` (the relay mux)."""
    heater_id: str
    enable: HalPin[bool]
    duty: HalPin[float]


@dataclass(frozen=True, slots=True)
class PidCalibratePins:
    heaters: tuple[PidTunePins, ...] = ()

    def of(self, heater_id: str) -> Optional[PidTunePins]:
        return next((h for h in self.heaters if h.heater_id == heater_id), None)


@dataclass(frozen=True, slots=True)
class ResonancePins:
    """``webgui.accel-record``: a CAN node's ADXL345 records while on (none
    for an accelerometer on the host's SPI)."""
    record: Optional[HalPin[bool]] = None


__all__ = ["PidCalibratePins", "PidTunePins", "ResonancePins", "ShaperPins"]
