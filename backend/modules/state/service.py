"""State module service — :class:`StateService` + :class:`MachineState`.

This is the canonical home for the machine-state / mode / MDI facade
that used to live on ``backend.services.machine_service.MachineControlService``.
The HTTP edge (``backend/modules/state/router.py``) is a thin wrapper
around :func:`get_state_service`; this module owns all business logic
and the operator-facing :class:`MachineState` enum.

The HTTP router imports only :func:`get_state_service` — never the
class directly — so the singleton lifecycle mirrors the historical
``get_machine_control_service`` pattern and a refactor of the
facade does not touch the router.
"""
from __future__ import annotations

import logging
import warnings
from enum import Enum
from typing import List, Optional

from hardware import connection
from hardware.connection import execute_sync_cmd, linuxcnc

logger = logging.getLogger("backend.modules.state.service")


# ---------------------------------------------------------------------------
# State facade enum — the clean, operator-facing vocabulary
# ---------------------------------------------------------------------------
#
# This enum is the single source of truth for the operator-facing
# machine state on the backend side. It mirrors
# ``frontend/src/stores/stateFacade.js::SystemState`` so the wire
# format stays in lockstep across the HTTP / WebSocket boundary.
#
# The values are lowercase strings (not the LinuxCNC NML integer
# constants) — that's the entire point of the facade: API consumers
# never see ``task_state == 1`` / ``task_state == 4`` integers and
# never have to import the ``linuxcnc`` module to interpret them.


class MachineState(str, Enum):
    """Operator-facing machine state.

    Mirrors ``frontend/src/stores/stateFacade.js::SystemState``.
    Values are lowercase strings rather than the LinuxCNC NML
    integer constants so the facade never leaks the underlying
    wire protocol. ``str``-mixin keeps the enum JSON-serialisable
    out of the box (``json.dumps(MachineState.IDLE) == '"idle"'``).
    """

    OFFLINE = "offline"
    ESTOP = "estop"
    POWER_OFF = "power_off"
    IDLE = "idle"
    LOADED = "loaded"
    RUNNING = "running"
    PAUSED = "paused"
    FAILURE = "failure"


class StateService:
    """Machine-business facade for state / mode / MDI.

    Each method is a thin wrapper over :func:`execute_sync_cmd` /
    :func:`execute_gcode` that translates the operator-facing string
    (e.g. ``"on"`` / ``"off"`` / ``"estop"``) to its NML integer
    constant before dispatching.
    """

    _STATE_CODES = {
        "on": "STATE_ON",
        "off": "STATE_OFF",
        "estop": "STATE_ESTOP",
        "estop_reset": "STATE_ESTOP_RESET",
    }
    _MODE_CODES = {
        "manual": "MODE_MANUAL",
        "auto": "MODE_AUTO",
        "mdi": "MODE_MDI",
    }

    @staticmethod
    def _resolve(table: dict, name: str) -> int:
        """Translate an operator-facing name to its NML integer.

        Missing entry → caller bug (``ValueError``); missing
        constant on the linuxcnc module → system misconfiguration
        (``RuntimeError``). Both bubble through ``execute_sync_cmd``'s
        own ``HTTPException(503)`` when the channel is offline.
        """
        attr = table.get(name)
        if attr is None:
            valid = ", ".join(sorted(table))
            raise ValueError(
                f"Unknown machine state / mode: {name!r}. "
                f"Expected one of: {valid}"
            )
        code = getattr(linuxcnc, attr, None)
        if code is None:
            raise RuntimeError(
                f"linuxcnc constant {attr!r} unavailable on this build"
            )
        return code

    def set_state(self, name: str) -> None:
        code = self._resolve(self._STATE_CODES, name)
        execute_sync_cmd("state", 3, code)
        warnings.warn(
            " is deprecated and will be removed "
            "use specific methode instead",
            DeprecationWarning,
            stacklevel=2
        )
        logger.info("dispatched machine state -> %s", name)

    def set_mode(self, name: str) -> None:
        code = self._resolve(self._MODE_CODES, name)
        execute_sync_cmd("mode", 5, code)
        logger.info("dispatched machine mode -> %s", name)

    def run_mdi(self, command: str) -> None:
        """Dispatch a single MDI command.

        Switches the task mode to ``MODE_MDI`` before issuing the
        command so a stale ``MODE_AUTO`` does not silently swallow
        the dispatch. The timeout (``5s``) is the historical
        ``mode`` round-trip budget.
        """
        logger.info("Running MDI: %s", command)
        execute_sync_cmd("mode", 5, getattr(linuxcnc, "MODE_MDI", 3))
        execute_sync_cmd("mdi", 1, command)

    def turn_machine_on(self) -> None:
        """Powers on the machine. Fails if ESTOP is active."""
        stat = connection.get_machine_stat()
        stat.poll()
        if getattr(stat, 'task_state', 0) == getattr(linuxcnc, "STATE_ESTOP", 1):
            raise RuntimeError("Cannot turn on machine while in E-STOP.")

        execute_sync_cmd("state", 3, getattr(linuxcnc, "STATE_ON", 3))

    def trigger_estop(self) -> None:
        """Forces an immediate emergency stop."""
        execute_sync_cmd("state", 3, getattr(linuxcnc, "STATE_ESTOP", 1))

    def get_state(self) -> MachineState:
        """Translate the linuxcnc ``task_state`` / ``estop`` /
        ``interp_state`` triple into a clean :class:`MachineState`.

        Priority order (mirrors
        ``frontend/src/stores/stateFacade.js::systemState``):

          OFFLINE → ESTOP → POWER_OFF → PAUSED → RUNNING →
          LOADED → IDLE → FAILURE.

        Returns :attr:`MachineState.OFFLINE` when:

          * the NML stat channel has not connected yet
            (``connection.get_machine_stat() is None``);
          * the stat object raises while we try to read it
            (mock-vs-real split, ``getattr(..., default)`` is
            the same defensive pattern used in
            ``routers/servo_thread.py::get_current_state``).

        The ``linuxcnc.STATE_*`` / ``INTERP_*`` constants are
        read via ``getattr(..., default)`` so a build that
        omits one of them degrades to the offline branch
        rather than crashing the request handler.
        """
        stat = connection.get_machine_stat()
        if stat is None:
            return MachineState.OFFLINE

        try:
            stat.poll()
            task_state = getattr(stat, "task_state", 0)
            estop = getattr(stat, "estop", 0)
            interp_state = getattr(stat, "interp_state", 0)
        except Exception:  # noqa: BLE001 - defensive, see docstring
            return MachineState.OFFLINE

        # E-stop bit wins over ``task_state`` — the operator
        # panel must always show ``Estop`` while the bit is set
        # even if LinuxCNC has not yet flipped ``task_state``.
        if estop == 1 or task_state == getattr(linuxcnc, "STATE_ESTOP", 1):
            return MachineState.ESTOP

        # ``STATE_OFF`` and ``STATE_ESTOP_RESET`` both surface
        # as ``POWER_OFF``: from the operator's point of view
        # the machine is not currently executing and not ready
        # to take a cut until they press Power.
        if task_state in (
            getattr(linuxcnc, "STATE_OFF", 3),
            getattr(linuxcnc, "STATE_ESTOP_RESET", 2),
        ):
            return MachineState.POWER_OFF

        if task_state == getattr(linuxcnc, "STATE_ON", 4):
            # ``STATE_ON`` covers the whole "powered" range; the
            # interpreter state disambiguates which sub-state
            # the operator actually sees.
            if interp_state == getattr(linuxcnc, "INTERP_PAUSED", 3):
                return MachineState.PAUSED
            if interp_state in (
                getattr(linuxcnc, "INTERP_READING", 2),
                getattr(linuxcnc, "INTERP_WAITING", 4),
            ):
                return MachineState.RUNNING
            # Interpreter idle while a file is selected — the
            # canonical LinuxCNC "loaded but not running" state.
            # The dashboard renders the dedicated ``Loaded``
            # branch with its own Start button.
            if getattr(stat, "file", ""):
                return MachineState.LOADED
            return MachineState.IDLE

        # Unknown ``task_state`` — defensive default rather than
        # crashing the WebSocket loop on a future LinuxCNC
        # build that adds a new state we don't know about yet.
        return MachineState.FAILURE

    def get_state_snapshot(self) -> dict:
        """JSON-serialisable snapshot for the API / WebSocket.

        Shape is deliberately stable::

            {
                "state": "idle",            # clean enum string
                "raw_task_state": 4,        # diagnostic-only
                "raw_estop": 0,
                "raw_interp_state": 1,
                "file": "",                 # loaded file path
                "homed": [0, 0, 0],         # per-axis flags
            }

        ``raw_*`` fields are intentionally prefixed so a future
        refactor can drop them without breaking the wire format.
        The clean ``state`` field is what every consumer should
        read; the raw fields exist only for the diagnostic panel
        and the migration window.
        """
        empty = {
            "state": MachineState.OFFLINE.value,
            "raw_task_state": 0,
            "raw_estop": 0,
            "raw_interp_state": 0,
            "file": "",
            "homed": [0, 0, 0],
        }

        stat = connection.get_machine_stat()
        if stat is None:
            return dict(empty)

        try:
            stat.poll()
            task_state = int(getattr(stat, "task_state", 0))
            estop = int(getattr(stat, "estop", 0))
            interp_state = int(getattr(stat, "interp_state", 0))
            file_name = getattr(stat, "file", "") or ""
            homed = list(getattr(stat, "homed", [0, 0, 0]))
        except Exception:  # noqa: BLE001 - defensive, see docstring
            return dict(empty)

        return {
            "state": self.get_state().value,
            "raw_task_state": task_state,
            "raw_estop": estop,
            "raw_interp_state": interp_state,
            "file": file_name,
            "homed": homed,
        }

    def get_machine_stat(self):
        warnings.warn(
            "StateService.get_machine_stat() is deprecated "
            "and will be removed — use get_state_snapshot() instead.",
            DeprecationWarning,
            stacklevel=2
        )
        return connection.get_machine_stat()

    def get_machine_cmd(self):
        warnings.warn(
            "StateService.get_machine_cmd() is deprecated "
            "and will be removed — dispatch helpers in this facade "
            "are the supported entry point.",
            DeprecationWarning,
            stacklevel=2
        )
        return connection.get_machine_cmd()

    def get_machine_error(self):
        warnings.warn(
            "StateService.get_machine_error() is deprecated "
            "and will be removed — error-channel handling will move "
            "to its own facade.",
            DeprecationWarning,
            stacklevel=2
        )
        return connection.get_machine_error()

    def is_linuxcnc_connected(self) -> bool:
        warnings.warn(
            "StateService.is_linuxcnc_connected() is "
            "deprecated and will be removed — the offline branch "
            "is exposed through get_state() == MachineState.OFFLINE.",
            DeprecationWarning,
            stacklevel=2
        )
        return connection.is_linuxcnc_connected()


_state_service: Optional[StateService] = None


def get_state_service() -> StateService:
    """Lazy module-level singleton (state / mode / MDI facade).

    Mirrors the historical :func:`backend.services.machine_service.get_machine_control_service`
    pattern. The instance survives across requests and resets on
    ``uvicorn --reload``.
    """
    global _state_service
    if _state_service is None:
        _state_service = StateService()
    return _state_service


__all__ = [
    "MachineState",
    "StateService",
    "get_state_service",
]