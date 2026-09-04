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
import time
import warnings
from enum import Enum
from typing import List, Optional, Any, Tuple

from fastapi import HTTPException
from pydantic import BaseModel

from dtos.EStopDto import EStopPin
from dtos.LinuxCNCError import now_iso
from dtos.pins.HalPin import HalDataType, HalPin
from dtos.pins.ReadWriteDynamicHalPin import ReadWriteDynamicHalPin
from dtos.pins.UnconnectedHalPin import UnconnectedHalPin
from hardware import execute_sync_cmd, linuxcnc, get_stat_channel, get_cmd_channel, is_linuxcnc_connected, \
    get_error_channel
from hardware.Connection import read_error_history

logger = logging.getLogger("backend.services.StateService")


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

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


class StateSnapshot(BaseModel):
    """JSON-serialisable snapshot for the API / WebSocket."""
    state: MachineState
    raw_task_state: int
    raw_estop: int
    raw_interp_state: int
    file: str
    homed: List[int]


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

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

    def __init__(self):
        self._Estop: EStopPin = None

    def preload_hal_pins(self):
        self._Estop = EStopPin("estop", ReadWriteDynamicHalPin("estop", HalDataType.BIT,""))

    def get_halpins(self) -> List[EStopPin]:
        """Returns the pre-built pin containers (mirrors ToolsService.get_halpins)."""
        if self._Estop is None:
            logging.warning("get_halpins() called before preload! Forcing late initialization.")
            self.preload_hal_pins()
        return [self._Estop]

    @staticmethod
    def _resolve(table: dict[str, str], name: str) -> int:
        """Translate an operator-facing name to its NML integer."""
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
        execute_sync_cmd("state", 3.0, code)
        warnings.warn(
            "StateService.set_state() is deprecated and will be removed. "
            "Use specific methods instead.",
            DeprecationWarning,
            stacklevel=2
        )
        logger.info("dispatched machine state -> %s", name)

    def set_mode(self, name: str) -> None:
        code = self._resolve(self._MODE_CODES, name)
        execute_sync_cmd("mode", 5.0, code)
        logger.info("dispatched machine mode -> %s", name)

    def run_mdi(self, command: str) -> None:
        """Dispatch a single MDI command."""
        logger.info("Running MDI: %s", command)
        execute_sync_cmd("mode", 5.0, getattr(linuxcnc, "MODE_MDI", 3))
        execute_sync_cmd("mdi", 1.0, command)

    def turn_machine_on(self) -> None:
        """Powers on the machine. Fails if ESTOP is active."""
        stat = get_stat_channel()
        if stat is None:
            raise RuntimeError("Cannot turn on machine: stat channel unavailable.")
        stat.poll()
        if getattr(stat, 'task_state', 0) == getattr(linuxcnc, "STATE_ESTOP", 1):
            raise RuntimeError("Cannot turn on machine while in E-STOP.")

        execute_sync_cmd("state", 3.0, getattr(linuxcnc, "STATE_ON", 3))

    def trigger_estop(self) -> None:
        """Forces an immediate emergency stop."""
        execute_sync_cmd("state", 3.0, getattr(linuxcnc, "STATE_ESTOP", 1))

    def activate_estop(self) -> None:

        """Critical e-stop activation — drives ``webgui.estop`` directly.

        We simply assert the custom software pin to True. The HAL layer is
        responsible for routing this to `halui.estop.activate` and generating
        the required rising edge (pulse) to ensure halui registers the command.
        """
        try:
            self._Estop.pressed.set_value(True)
        except Exception as e:
            raise HTTPException(
                status_code=503,
                detail=f"HAL unreachable — cannot set webgui.estop: {e}"
            )

    def get_state(self) -> MachineState:
        """Translate the linuxcnc stat triple into a clean MachineState."""
        stat = get_stat_channel()
        if stat is None:
            return MachineState.OFFLINE

        try:
            stat.poll()
            task_state = getattr(stat, "task_state", 0)
            estop = getattr(stat, "estop", 0)
            interp_state = getattr(stat, "interp_state", 0)
        except Exception:  # noqa: BLE001 - defensive, see docstring
            return MachineState.OFFLINE

        if estop == 1 or task_state == getattr(linuxcnc, "STATE_ESTOP", 1):
            return MachineState.ESTOP

        if task_state in (
            getattr(linuxcnc, "STATE_OFF", 3),
            getattr(linuxcnc, "STATE_ESTOP_RESET", 2),
        ):
            return MachineState.POWER_OFF

        if task_state == getattr(linuxcnc, "STATE_ON", 4):
            if interp_state == getattr(linuxcnc, "INTERP_PAUSED", 3):
                return MachineState.PAUSED
            if interp_state in (
                getattr(linuxcnc, "INTERP_READING", 2),
                getattr(linuxcnc, "INTERP_WAITING", 4),
            ):
                return MachineState.RUNNING
            if getattr(stat, "file", ""):
                return MachineState.LOADED
            return MachineState.IDLE

        return MachineState.FAILURE

    def get_state_snapshot(self) -> StateSnapshot:
        """Return a strictly-typed snapshot of the current machine state."""
        empty_defaults = {
            "state": MachineState.OFFLINE,
            "raw_task_state": 0,
            "raw_estop": 0,
            "raw_interp_state": 0,
            "file": "",
            "homed": [0, 0, 0],
        }

        stat = get_stat_channel()
        if stat is None:
            return StateSnapshot(**empty_defaults)

        try:
            stat.poll()
            return StateSnapshot(
                state=self.get_state(),
                raw_task_state=int(getattr(stat, "task_state", 0)),
                raw_estop=int(getattr(stat, "estop", 0)),
                raw_interp_state=int(getattr(stat, "interp_state", 0)),
                file=getattr(stat, "file", "") or "",
                homed=list(getattr(stat, "homed", [0, 0, 0]))
            )
        except Exception:  # noqa: BLE001
            return StateSnapshot(**empty_defaults)

    def get_machine_stat(self):
        warnings.warn(
            "StateService.get_machine_stat() is deprecated "
            "and will be removed — use get_state_snapshot() instead.",
            DeprecationWarning,
            stacklevel=2
        )
        return get_stat_channel()

    def get_machine_cmd(self):
        warnings.warn(
            "StateService.get_machine_cmd() is deprecated "
            "and will be removed — dispatch helpers in this facade "
            "are the supported entry point.",
            DeprecationWarning,
            stacklevel=2
        )
        return get_cmd_channel()

    def get_machine_error(self):
        warnings.warn(
            "StateService.get_machine_error() is deprecated "
            "and will be removed — error-channel handling will move "
            "to its own facade.",
            DeprecationWarning,
            stacklevel=2
        )
        return get_error_channel()

    def is_linuxcnc_connected(self) -> bool:
        warnings.warn(
            "StateService.is_linuxcnc_connected() is "
            "deprecated and will be removed — the offline branch "
            "is exposed through get_state() == MachineState.OFFLINE.",
            DeprecationWarning,
            stacklevel=2
        )
        return is_linuxcnc_connected()

    def get_polled_stat(self) -> Optional[Any]:
        """Safely poll and return the raw stat object, suppressing transient OS errors."""
        stat = get_stat_channel()
        if not stat:
            return None
        try:
            stat.poll()
            return stat
        except (OSError, RuntimeError) as exc:
            logger.debug("stat.poll() failed (%s); returning unpolled/None", exc)
            return None

    def drain_new_errors(self, limit: int = 256) -> List[Tuple[int, str]]:
        """Safely drain pending events from the error channel up to a limit."""
        err_ch = get_error_channel()
        if not err_ch:
            return []

        pending: List[Tuple[int, str]] = []
        try:
            while len(pending) < limit:
                entry = err_ch.poll()
                if entry is None:
                    break
                pending.append(entry)

            if len(pending) == limit:
                logger.warning("error_channel drained %d events (cap reached).", limit)

        except (OSError, RuntimeError) as exc:
            logger.debug("error_channel.poll() iteration raised %s", exc)

        return pending

    def record_error_to_mock(self, kind: int, text: str) -> None:
        """Mirror an error to the mock's bounded history (no-op on real hardware)."""
        stat = get_stat_channel()
        if not stat:
            return

        push_error = getattr(stat, "push_error", None)
        if callable(push_error):
            try:
                push_error(text=text, kind=kind, time=now_iso())
            except TypeError:
                # Legacy positional signature fallback
                push_error(kind, text, now_iso())
            except Exception as exc:  # noqa: BLE001
                logger.debug("push_error mirror failed: %s", exc)

    def get_error_history(self) -> List[str]:
        """Fetch the full error history buffer."""
        return read_error_history()




_state_service: Optional[StateService] = None


def get_state_service() -> StateService:
    """Lazy module-level singleton (state / mode / MDI facade)."""
    global _state_service
    if _state_service is None:
        _state_service = StateService()
    return _state_service


__all__ = [
    "MachineState",
    "StateSnapshot",
    "StateService",
    "get_state_service",
]