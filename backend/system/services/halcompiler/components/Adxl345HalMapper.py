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

from typing import Any

from mappers.machineconfig import PinStringMapper
from models.machineconfig.HalFragmentModels import SERVO_THREAD, Addf, HalFragment, PinRequest, PinRole

SIGNAL = "adxl345"
SAMPLER = "sampler.0"
#: Samples the sampler's FIFO holds: 4 s at 1 kHz between two reads.
SAMPLER_DEPTH = 4000


def _bare(pin: Any) -> str | None:
    return PinStringMapper.from_string(str(pin)).pin_id if pin else None


class Adxl345HalMapper:
    @staticmethod
    def node_adxl345(payload: dict[str, Any]) -> dict[str, Any] | None:
        """The ``[adxl345]`` section when it sits on a CAN node (``cs_pin``)."""
        adxl = payload.get("adxl345")
        return adxl if isinstance(adxl, dict) and adxl.get("cs_pin") else None

    @staticmethod
    def to_fragment(payload: dict[str, Any]) -> HalFragment:
        fragment = HalFragment()
        adxl = Adxl345HalMapper.node_adxl345(payload)
        if adxl is None:
            return fragment
        fragment.requests.append(PinRequest(
            signal=SIGNAL,
            role=PinRole.ACCEL,
            pin=PinStringMapper.from_string(str(adxl["cs_pin"])),
            owner="adxl345",
            accel=(str(adxl.get("axes_map") or "x,y,z"), int(adxl.get("rate") or 3200),
                   _bare(adxl.get("sclk_pin")), _bare(adxl.get("mosi_pin")), _bare(adxl.get("miso_pin"))),
        ))
        fragment.loadrt.append(f"loadrt sampler depth={SAMPLER_DEPTH} cfg=ff")
        fragment.addf.append(Addf(SAMPLER, SERVO_THREAD, order=2))
        fragment.nets.append(f"net {SIGNAL}-x => {SAMPLER}.pin.0")
        fragment.nets.append(f"net {SIGNAL}-y => {SAMPLER}.pin.1")
        return fragment


__all__ = ["Adxl345HalMapper", "SAMPLER", "SAMPLER_DEPTH", "SIGNAL"]
