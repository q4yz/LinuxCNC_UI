import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# HAL Subscription Manager (Layer 0: Hardware State Monitoring)
# ---------------------------------------------------------------------------
#
# The HAL availability flag (``HAS_HAL``), the imported HAL module
# reference (``hal``), and the mock-mode flag (``USE_MOCK``) all
# live in :mod:`backend.hardware.connection` — the file that owns
# the import dance against the optional ``hal`` Python binding.
# Importing them at module load time here would re-enter
# ``hardware.connection`` while it is still initialising
# ``hal_subscription_manager`` itself (the re-export at the
# bottom of that module pulls us in eagerly), so the imports are
# deferred to ``read_pin`` — the only consumer that needs them.
# By the time ``read_pin`` runs, ``hardware.connection`` has
# finished initialising and the deferred relative import resolves
# cleanly.


class HalSubscriptionManager:
    """Polls HAL pin states and notifies callbacks on state changes.

    ``hal.get_value(pin_name)`` returns the current value of a HAL
    signal — a boolean for digital pins, a float for analogue.
    The manager polls every ``poll_interval`` seconds and fires
    every registered callback only when the value changes, so a
    busy pin does not flood the consumer thread.

    The mock fallback (``hal is None`` or ``USE_MOCK``) returns
    ``False`` for every read so the poll loop still runs (a real
    subscription manager) but never fires spurious callbacks — the
    frontend's endstop panel renders an empty / "offline" state
    until the real HAL module is importable.
    """

    def __init__(self, poll_interval: float = 0.1) -> None:
        self._poll_interval = poll_interval
        self._subscriptions: Dict[str, List[Callable[[Any], None]]] = {}
        self._last_known_states: Dict[str, Any] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def subscribe(self, pin_name: str, callback: Callable[[Any], None]) -> None:
        """Register a callback to fire when a HAL pin value changes.

        The callback fires on every poll where the value differs
        from the last-known state. Subscribing twice to the same
        pin appends the second callback to the fan-out list; the
        pin is read at most once per poll.
        """
        if pin_name not in self._subscriptions:
            self._subscriptions[pin_name] = []
            self._last_known_states[pin_name] = self.read_pin(pin_name)
        self._subscriptions[pin_name].append(callback)

    def read_pin(self, pin_name: str) -> Any:
        """Read current pin value directly.

        Returns ``None`` when the HAL module is unavailable so the
        consumer can render a "HAL offline" indicator without
        crashing. Real HAL signals come through as their Python
        type (``bool`` for digital, ``float`` for analogue).
        """
        # Deferred import — see the module-level comment. ``HAS_HAL``
        # and friends live in :mod:`hardware.connection` which is
        # still initialising when this module is first loaded, so a
        # top-level ``from .connection import HAS_HAL`` would loop
        # back into a partially initialised module and raise.
        from .connection import HAS_HAL, USE_MOCK, hal

        if HAS_HAL and hal is not None and not USE_MOCK:
            try:
                return hal.get_value(pin_name)
            except Exception as e:
                logger.error("Error reading HAL pin %s: %s", pin_name, e)
                return None
        # Mock fallback — every pin reads ``False`` until the real
        # HAL module is importable. Frontend widgets render the
        # "offline" branch off this signal.
        return False

    def start(self) -> None:
        """Start the background poll thread (idempotent).

        The thread is a daemon so it cannot block process exit.
        Multiple calls are safe — the ``self._running`` guard
        short-circuits a second ``start()`` so a hot-reload doesn't
        stack poll loops.
        """
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the background poll thread (idempotent).

        Safe to call when the thread was never started or has
        already exited — the ``self._running`` flag short-circuits
        the join.
        """
        self._running = False
        if self._thread is not None:
            self._thread.join()

    def _poll_loop(self) -> None:
        """Poll every subscribed pin and fire callbacks on change.

        Runs until ``self._running`` flips to ``False``. A per-pin
        exception in a callback is logged and isolated so one bad
        subscriber cannot stop the others from firing.
        """
        while self._running:
            for pin_name, callbacks in list(self._subscriptions.items()):
                val = self.read_pin(pin_name)
                if val != self._last_known_states.get(pin_name):
                    self._last_known_states[pin_name] = val
                    for cb in callbacks:
                        try:
                            cb(val)
                        except Exception as e:
                            logger.error(
                                "Error in HAL callback for %s: %s",
                                pin_name,
                                e,
                            )
            time.sleep(self._poll_interval)


# Module-level HAL subscription manager — the singleton
# ``HalSubscriptionManager`` is process-lifetime. ``start()`` is
# called explicitly by an owning consumer (a future HAL-pin
# subscription endpoint) rather than at import time so the daemon
# thread does not fire before the operator asks for it.
hal_manager = HalSubscriptionManager()