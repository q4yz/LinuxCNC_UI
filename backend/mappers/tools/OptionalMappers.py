from typing import Any, Optional, Union

class OptionalMappers:

    @classmethod
    def as_float(cls, value: Any) -> float:
        try:
            return float(value) if value is not None else 0.0
        except (ValueError, TypeError):
            return 0.0

    @classmethod
    def as_int(cls, value: Any) -> int:
        try:
            return int(value) if value is not None else 0
        except (ValueError, TypeError):
            return 0

    @classmethod
    def as_bool(cls, value: Any) -> bool:
        return bool(value) if value is not None else False

    @classmethod
    def as_str(cls, value: Any) -> str:
        return str(value) if value is not None else ""

    @classmethod
    def as_optional_float(cls, value: Any) -> Optional[float]:
        """Returns ``None`` when the pin is unconnected / not yet known.

        Use this for values that should round-trip as ``null`` on the
        wire so the frontend can distinguish "HAL has not streamed
        anything" from a real numeric zero (e.g. override RPM before
        the first user command).
        """
        if value is None:
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None

    @classmethod
    def as_optional_int(cls, value: Any) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None


    @classmethod
    def as_optional_number(cls, value: Any, num_type: type) -> Optional[Union[int, float]]:
        if isinstance(value, (int, float)):
            return num_type(value)
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return None
            try:
                return num_type(float(value))
            except ValueError:
                return None
        return None