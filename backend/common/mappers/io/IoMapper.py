"""IO: pins from the profile, the state DTO, the response."""
from __future__ import annotations

from typing import Any, Dict, Iterable

from dtos.fans.FanDto import FanPins
from dtos.io.IoDto import (
    IoFanDTO,
    IoInputDTO,
    IoInputPins,
    IoOutputDTO,
    IoOutputPins,
    IoPins,
    IoStateDTO,
)
from dtos.pins.HalPin import HalDataType, HalPin
from dtos.pins.ReadOnlyDynamicHalPin import ReadOnlyDynamicHalPin
from dtos.pins.ReadWriteDynamicHalPin import ReadWriteDynamicHalPin
from models.IoModels import IoFan, IoInput, IoOutput, IoState


class IoMapper:
    @staticmethod
    def from_dict_to_IoPins(payload: Dict[str, Any]) -> IoPins:
        """``hardware.json``'s ``output_pins`` / ``input_pins``. An output an
        input sets (``*_halpin_set``) is latched in HAL: a float pin plus
        its ``-set`` / ``-state`` pins; otherwise a PWM output is a float, a
        switched one a bit."""
        latched = {
            str(entry.get("output"))
            for inp in payload.get("input_pins") or []
            for edge in ("rising", "falling")
            for entry in inp.get(f"{edge}_halpin_set") or []
        }
        outputs = []
        for out in payload.get("output_pins") or []:
            pin_id = str(out["id"])
            latch = pin_id in latched
            hal_type = HalDataType.FLOAT if out.get("pwm") or latch else HalDataType.BIT
            pin: HalPin[Any] = ReadWriteDynamicHalPin(pin_id, hal_type, f"Output pin {pin_id}")
            outputs.append(IoOutputPins(
                id=pin_id,
                pin=pin,
                pwm=bool(out.get("pwm")),
                scale=float(out.get("scale") or 1.0),
                start_value=float(out.get("value") or 0.0),
                latch_set=ReadWriteDynamicHalPin(f"{pin_id}-set", HalDataType.BIT, f"Output pin {pin_id}: apply")
                if latch else None,
                latch_state=ReadOnlyDynamicHalPin(f"{pin_id}-state", HalDataType.FLOAT, f"Output pin {pin_id}: value")
                if latch else None,
            ))
        inputs = [
            IoInputPins(id=str(inp["id"]), pin=ReadOnlyDynamicHalPin(str(inp["id"]), HalDataType.BIT, f"Input pin {inp['id']}"))
            for inp in payload.get("input_pins") or []
        ]
        return IoPins(outputs=tuple(outputs), inputs=tuple(inputs))

    @staticmethod
    def output_value(out: IoOutputPins) -> float:
        """What the output is now: a latched one reads its ``-state``."""
        pin: HalPin[Any] = out.latch_state if out.latch_state is not None else out.pin
        return float(pin.get_value() or 0.0)

    @staticmethod
    def to_state_dto(pins: IoPins, fans: Iterable[FanPins]) -> IoStateDTO:
        return IoStateDTO(
            fans=tuple(IoFanDTO(id=fan.id, value=float(fan.speed.get_value() or 0.0)) for fan in fans),
            outputs=tuple(IoOutputDTO(id=o.id, pwm=o.pwm, scale=o.scale, value=IoMapper.output_value(o))
                          for o in pins.outputs),
            inputs=tuple(IoInputDTO(id=i.id, value=bool(i.pin.get_value())) for i in pins.inputs),
        )

    @staticmethod
    def to_response(dto: IoStateDTO) -> IoState:
        return IoState(
            fans=[IoFan(id=f.id, value=f.value) for f in dto.fans],
            outputs=[IoOutput(id=o.id, pwm=o.pwm, scale=o.scale, value=o.value) for o in dto.outputs],
            inputs=[IoInput(id=i.id, value=i.value) for i in dto.inputs],
        )


__all__ = ["IoMapper"]
