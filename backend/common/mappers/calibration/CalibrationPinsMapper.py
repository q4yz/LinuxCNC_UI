"""The calibration services' pins (see ``dtos.calibration.CalibrationPinsDto``)."""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from dtos.calibration.CalibrationPinsDto import PidCalibratePins, PidTunePins, ResonancePins, ShaperPins
from dtos.pins.HalPin import HalDataType
from dtos.pins.ReadWriteDynamicHalPin import ReadWriteDynamicHalPin


class ShaperMapper:
    @staticmethod
    def create_ShaperPins() -> ShaperPins:
        def pin(name: str) -> ReadWriteDynamicHalPin[float]:
            return ReadWriteDynamicHalPin(name, HalDataType.FLOAT, f"jointshape: {name}")

        return ShaperPins(
            shaper_freq_x=pin("shaper-freq-x"),
            shaper_freq_y=pin("shaper-freq-y"),
            skew_xy=pin("skew-xy"),
            resonance_amp_x=pin("resonance-amp-x"),
            resonance_amp_y=pin("resonance-amp-y"),
            resonance_freq=pin("resonance-freq"),
        )


class PidCalibrateMapper:
    @staticmethod
    def from_dict_to_PidCalibratePins(heaters: Iterable[Mapping[str, Any]]) -> PidCalibratePins:
        """The PID heaters of ``hardware.json`` (``tools`` with ``control: pid``)."""
        return PidCalibratePins(heaters=tuple(
            PidTunePins(
                heater_id=str(h["id"]),
                enable=ReadWriteDynamicHalPin(f"tune-{h['id']}-enable", HalDataType.BIT, f"PID_CALIBRATE: {h['id']} on the relay"),
                duty=ReadWriteDynamicHalPin(f"tune-{h['id']}-duty", HalDataType.FLOAT, f"PID_CALIBRATE: {h['id']} duty (%)"),
            )
            for h in heaters
        ))


class ResonanceMapper:
    @staticmethod
    def create_ResonancePins(record_pin: str | None) -> ResonancePins:
        """``record_pin``: the node accelerometer's record pin name, ``None``
        for an ADXL345 on the host's SPI (no pin)."""
        if record_pin is None:
            return ResonancePins()
        return ResonancePins(record=ReadWriteDynamicHalPin(
            record_pin, HalDataType.BIT, "Resonance test: record the node accelerometer"))


__all__ = ["PidCalibrateMapper", "ResonanceMapper", "ShaperMapper"]
