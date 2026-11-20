from typing import Any, Callable, Dict, Optional


class MockComponent:
    """Base class for the mock's simulated hardware.

    A component owns a slice of the HAL pin namespace: ``_pin_map`` maps
    each full pin name (``webgui.bed``) to the attribute holding its
    value, and ``_pin_cast`` converts a written value (``float`` for
    analog pins; ``None`` keeps it as written). Subclasses fill the map
    and add their physics in :meth:`update`.
    """

    id: Optional[str] = None
    _pin_map: Dict[str, str] = {}
    _pin_cast: Optional[Callable[[Any], Any]] = None

    def read_pin(self, pin_name: str) -> Optional[Any]:
        """The pin's value if this component owns it, else ``None``."""
        attr = self._pin_map.get(pin_name)
        return None if attr is None else getattr(self, attr)

    def set_pin(self, pin_name: str, value: Any) -> bool:
        """Store a written value. ``True`` if this component owns the pin."""
        attr = self._pin_map.get(pin_name)
        if attr is None:
            return False
        cast = type(self)._pin_cast
        setattr(self, attr, cast(value) if cast else value)
        return True

    def execute_mdi(self, gcode: str) -> bool:
        """React to an MDI line (``M3``, ``G1 E…``). ``True`` if handled."""
        return False

    def update(self, hal, nml, delta_time: float) -> None:
        """Simulate one tick (heating up, spinning up)."""
