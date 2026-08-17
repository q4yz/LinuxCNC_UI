import logging
import threading
from typing import Any, Dict, List

logger = logging.getLogger(__name__)
class HalMock:
    """The 'Muscle' of the LinuxCNC simulation.

    Acts as the central registry for physical states (pins) and active
    hardware components (spindles, heaters). It is completely decoupled
    from G-code or HTTP endpoints.
    """

    def __init__(self, nml_state):
        self.lock = threading.Lock()
        self.pins: Dict[str, Any] = {}
        self._components: List[Any] = []
        self.nml = nml_state

    def register_component(self, component):
        """Add a hardware component to the simulation loop."""
        with self.lock:
            new_id = getattr(component, "id", None)

            # If it has an ID, filter out any existing component with the same ID
            if new_id:
                # Count before filtering so we know if we overwrote something
                old_count = len(self._components)

                self._components = [
                    c for c in self._components
                    if getattr(c, "id", None) != new_id
                ]

                if len(self._components) < old_count:
                    logger.info(f"Replaced existing component with ID: '{new_id}'")
                else:
                    logger.info(f"Registered new component with ID: '{new_id}'")
            else:
                logger.info(f"Registered anonymous component without an ID: {component.__class__.__name__}")

            # Add the fresh component
            self._components.append(component)

    def set_pin(self, name: str, value: Any):
        """Write a value to a HAL pin."""
        with self.lock:
            self.pins[name] = value

    def get_pin(self, name: str, default: Any = 0.0) -> Any:
        """Read a value from a HAL pin, returning a safe default if missing."""
        with self.lock:
            return self.pins.get(name, default)

    def update(self, delta_time: float = 0.1):
        """The internal hardware tick.

        Iterates through all registered components and tells them to process
        their physics/logic for this timeframe.
        """
        with self.lock:
            for component in self._components:
                component.update(hal=self, nml=self.nml, delta_time=delta_time)


