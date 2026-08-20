import logging

logger = logging.getLogger(__name__)


class MockComponent:
    """Mocks a LinuxCNC HAL component so Windows development doesn't crash."""

    def __init__(self, name: str, internal_hal):
        self.internal_hal = internal_hal
        self.name = name
        self.is_ready = False
        self._pins = {}  # Internal dictionary to store pin values

    def newpin(self, pin_name: str, pin_type: int, pin_dir: int):
        """Mocks creating a new pin."""
        self._pins[pin_name] = 0.0  # Initialize with a default value
        logger.debug("MOCK HAL: Created pin %s.%s (Type: %s, Dir: %s)",
                     self.name, pin_name, pin_type, pin_dir)

    def ready(self):
        """Mocks locking the component."""
        self.is_ready = True
        logger.debug("MOCK HAL: Component '%s' is ready.", self.name)

    def exit(self):
        """Mocks shutting down the component."""
        logger.debug("MOCK HAL: Component '%s' exited.", self.name)

    # --- Magic methods to allow comp["pin_name"] = value ---

    def __setitem__(self, pin_name: str, value):
        """Allows writing to the pin like: comp['override'] = 5.0"""
        if pin_name not in self._pins:
            logger.warning("MOCK HAL: Writing to unassigned pin '%s'", pin_name)
        self._pins[pin_name] = value
        logger.info("MOCK HAL Write: %s.%s = %s", self.name, pin_name, value)

    def __getitem__(self, pin_name: str):
        """Allows reading from the pin like: val = comp['override']"""
        return self._pins.get(pin_name, 0.0)