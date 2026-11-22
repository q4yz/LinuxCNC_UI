"""``[adxl345] cs_pin: <node>:PB12`` -> the ADXL345 of a CAN node
(Remora-m8p ``CAN_PROTOCOL.md`` § Accelerometer).

The node reads the sensor; the hub writes the machine X / Y accelerations
(mm/s², the node's ``axes_map`` applied) into two process variables. The
pin request makes the Remora router pick them and write the node's
``ADXL345`` module; this fragment records them every servo period in a
``sampler`` the machine backend reads with ``halsampler`` (the resonance
test, ``ResonanceService``)::

    net adxl345-x <= remora.PV.3          (router)
    net adxl345-y <= remora.PV.4
    loadrt sampler depth=4000 cfg=ff
    addf sampler.0 servo-thread
    net adxl345-x => sampler.0.pin.0
    net adxl345-y => sampler.0.pin.1

    webgui_connections.hal:
    net adxl345-record webgui.accel-record => sampler.0.enable

Without ``cs_pin`` the backend reads an ADXL345 on the host's SPI itself:
no HAL at all.
"""
from __future__ import annotations

from mappers.machineconfig import PinStringMapper
from models.machineconfig.HardwareJsonModels import Adxl345
from models.machineconfig.HalFragmentModels import SERVO_THREAD, Addf, HalFragment, PinRequest, PinRole

SIGNAL = "adxl345"
SAMPLER = "sampler.0"
#: Samples the sampler's FIFO holds: 4 s at 1 kHz between two reads.
SAMPLER_DEPTH = 4000


def _bare(pin: str | None) -> str | None:
    return PinStringMapper.from_string(pin).pin_id if pin else None


class Adxl345HalMapper:
    @staticmethod
    def on_node(adxl: Adxl345 | None) -> bool:
        """The accelerometer sits on a CAN node (``cs_pin``), not the host's SPI."""
        return adxl is not None and bool(adxl.cs_pin)

    @staticmethod
    def to_fragment(adxl: Adxl345 | None) -> HalFragment:
        fragment = HalFragment()
        if adxl is None or not adxl.cs_pin:
            return fragment
        fragment.requests.append(PinRequest(
            signal=SIGNAL,
            role=PinRole.ACCEL,
            pin=PinStringMapper.from_string(adxl.cs_pin),
            owner="adxl345",
            accel=(adxl.axes_map, adxl.rate, _bare(adxl.sclk_pin), _bare(adxl.mosi_pin), _bare(adxl.miso_pin)),
        ))
        fragment.loadrt.append(f"loadrt sampler depth={SAMPLER_DEPTH} cfg=ff")
        fragment.addf.append(Addf(SAMPLER, SERVO_THREAD, order=2))
        fragment.nets.append(f"net {SIGNAL}-x => {SAMPLER}.pin.0")
        fragment.nets.append(f"net {SIGNAL}-y => {SAMPLER}.pin.1")
        return fragment


__all__ = ["Adxl345HalMapper", "SAMPLER", "SAMPLER_DEPTH", "SIGNAL"]
