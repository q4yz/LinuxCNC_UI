from typing import TypeVar, Type, Optional, Union

from modules.tools.dtos import SpindleDigitalPins, SpindleAnalogPins, HeaterPins, ExtruderPins

T = TypeVar('T')
AnyToolPin = Union[ExtruderPins, HeaterPins, SpindleAnalogPins, SpindleDigitalPins]


class ToolPinTypeFactory:
    @staticmethod
    def create(data: AnyToolPin, expected_type: Type[T]) -> Optional[T]:

        if expected_type is ExtruderPins:
            if isinstance(data, ExtruderPins):
                return data

        if expected_type is HeaterPins:
            if isinstance(data, ExtruderPins):
                return data.heater
            if isinstance(data, HeaterPins):
                return data

        if expected_type is SpindleDigitalPins:
            if isinstance(data, SpindleDigitalPins):
                return data

        if expected_type is SpindleAnalogPins:
            if isinstance(data, SpindleAnalogPins):
                return data

        return None