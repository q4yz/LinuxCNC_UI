import logging
import threading
from typing import Any, Callable, Dict, List

logger = logging.getLogger(__name__)


class HalMock:
    """The 'Muscle' of the simulation: every HAL pin's value.

    A pin owned by a registered component (a heater's target and
    reading, the E-stop) is answered by that component, which also
    simulates it. Every other pin is kept in a plain store: a value
    written (a fan's speed, an LED colour, an output pin, a tuning
    value) reads back as written, as on a real HAL signal. Unknown pins
    read as ``default``.
    """

    def __init__(self, nml_state: Any) -> None:
        self.lock = threading.RLock()
        self._components: List[Any] = []
        self._pins: Dict[str, Any] = {}
        self.nml = nml_state

    # -- components ---------------------------------------------------------- #

    def register_component(self, component):
        """Add a component; one with the same ``id`` is replaced."""
        with self.lock:
            new_id = getattr(component, "id", None)
            if new_id:
                before = len(self._components)
                self._components = [c for c in self._components if getattr(c, "id", None) != new_id]
                verb = "Replaced" if len(self._components) < before else "Registered"
                logger.debug("%s mock component '%s'", verb, new_id)
            self._components.append(component)

    def remove_components(self, predicate: Callable[[Any], bool]) -> None:
        with self.lock:
            self._components = [c for c in self._components if not predicate(c)]

    @property
    def components(self) -> List[Any]:
        with self.lock:
            return list(self._components)

    # -- pins ------------------------------------------------------------------ #

    def set_pin(self, name: str, value: Any) -> None:
        """Write a pin: its owning component(s) take it, else the store."""
        with self.lock:
            handled = False
            for component in self._components:
                if component.set_pin(name, value):
                    handled = True
            if not handled:
                self._pins[name] = value
        logger.debug("pin '%s' = %r (%s)", name, value, "component" if handled else "store")

    def get_pin(self, name: str, default: Any = 0.0) -> Any:
        """Read a pin: a component's live value first, then the store."""
        with self.lock:
            for component in self._components:
                value = component.read_pin(name)
                if value is not None:
                    return value
            return self._pins.get(name, default)

    @property
    def pins(self) -> Dict[str, Any]:
        """A copy of the stored (component-less) pin values."""
        with self.lock:
            return dict(self._pins)

    def clear_pins(self) -> None:
        with self.lock:
            self._pins.clear()

    # -- tick ------------------------------------------------------------------ #

    def update(self, delta_time: float = 0.1):
        """One tick of every component's physics."""
        with self.lock:
            for component in self._components:
                component.update(hal=self, nml=self.nml, delta_time=delta_time)

    def execute_mdi(self, cmd: str) -> bool:
        """Offer an MDI line to every component. ``True`` if one handled it."""
        with self.lock:
            return any([component.execute_mdi(cmd) for component in self._components])
