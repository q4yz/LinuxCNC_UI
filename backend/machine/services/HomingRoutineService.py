"""Homing routine — runs a machine's ``[homing_override]``
(`.agent/component/homing_override.md`).

LinuxCNC cannot home from G-code: homing needs MANUAL mode and a
program runs in AUTO. So the routine (``hardware.json``'s
``homing_override.gcode``) runs here, one line at a time, on a worker
thread like a macro (:class:`MacroExecutionService`):

* ``G28 X`` — MANUAL mode, ``home(<joint of X>)``, wait until every
  joint of X is homed (a gantry's twin joints home together through
  their shared negative ``HOME_SEQUENCE``);
* ``G28`` — ``home(-1)``: every joint by ``HOME_SEQUENCE``;
* anything else — MDI, waiting until the interpreter is idle again.

The routine stops at the first failure (E-stop, machine off, a line
LinuxCNC rejects, a joint that stops homing without being homed, a
timeout) and says why in the console log. The generator sets
``[TRAJ] NO_FORCE_HOMING = 1`` for such a machine so the routine's
moves run before every joint is homed; :meth:`require_homed` keeps a
program from starting on a machine that is not.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from core.homing_routine import HomingStep, parse_homing_routine
from exceptions import BadRequestError, ConflictError
from hardware import dispatch_mdi, get_stat_channel, linuxcnc
from hardware.Connection import MachineState, execute_sync_cmd
from services.ConsoleLogger import LogLevel, get_console_logger
from services.HardwareConfigService import HardwareConfigService
from services.MacroExecutionService import MacroExecutionService, get_macro_execution_service

logger = logging.getLogger("backend.services.HomingRoutineService")

_MODE_MANUAL = getattr(linuxcnc, "MODE_MANUAL", 1)
_POLL_S = 0.05
#: Longest a single home step may take (slow search + latch on a long axis).
HOME_TIMEOUT_S = 180.0
#: A joint that is neither homed nor homing this long after ``home()``
#: never started — LinuxCNC refused it (the reason is on its error channel).
HOME_START_GRACE_S = 2.0


class HomingRoutineService:
    """Runs the machine's homing routine; one at a time."""

    def __init__(
        self,
        config: Optional[HardwareConfigService] = None,
        macros: Optional[MacroExecutionService] = None,
        joints_of: Optional[Callable[[str], List[int]]] = None,
    ) -> None:
        self._config = config or HardwareConfigService()
        self._macros = macros
        self._joints_of = joints_of
        self._worker: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    # -- configuration ---------------------------------------------------- #

    def override(self) -> Optional[Dict[str, Any]]:
        """``hardware.json``'s ``homing_override``, or ``None``."""
        value = self._config.load_payload().get("homing_override")
        return value if isinstance(value, dict) and value.get("gcode") else None

    def applies_to(self, axis: str) -> bool:
        """Does homing ``axis`` (a letter, or ``"all"``) run the routine?"""
        override = self.override()
        if override is None:
            return False
        return axis == "all" or axis.lower() in str(override.get("axes") or "")

    def _axis_joints(self, letter: str) -> List[int]:
        if self._joints_of is not None:
            return self._joints_of(letter)
        for axis in self._config.get_axes():
            if str(axis.get("id", "")).lower() == letter.lower():
                return [int(j) for j in axis.get("joint_numbers") or []]
        return []

    def _all_joints(self) -> List[int]:
        return sorted({j for axis in self._config.get_axes() for j in axis.get("joint_numbers") or []})

    # -- running ---------------------------------------------------------- #

    def is_running(self) -> bool:
        worker = self._worker
        return worker is not None and worker.is_alive()

    def join(self, timeout: Optional[float] = None) -> None:
        worker = self._worker
        if worker is not None:
            worker.join(timeout)

    def start(self) -> None:
        """Check the machine and start the routine on a worker thread;
        returns at once. Progress and failures go to the console log."""
        override = self.override()
        if override is None:
            raise BadRequestError("This machine has no [homing_override] routine.")
        steps = parse_homing_routine(str(override["gcode"]))

        stat = get_stat_channel()
        if stat is None:
            raise BadRequestError("Cannot home: LinuxCNC is not running.")
        stat.poll()
        if stat.estop:
            raise BadRequestError("Cannot home while the machine is in E-STOP.")
        if stat.task_state != MachineState.ON.value:
            raise BadRequestError("Turn the machine on before homing.")
        macros = self._macros or get_macro_execution_service()
        if macros.is_running():
            raise ConflictError("A macro is still running.")

        with self._lock:
            if self.is_running():
                raise ConflictError("The homing routine is already running.")
            self._worker = threading.Thread(
                target=self._run_worker, args=(steps,), name="homing-routine", daemon=True
            )
            self._worker.start()

    def _run_worker(self, steps: List[HomingStep]) -> None:
        console = get_console_logger()
        try:
            reason = self._run(steps)
        except Exception as exc:  # noqa: BLE001 - report, don't die silently
            logger.exception("Homing routine crashed: %s", exc)
            reason = str(exc)
        if reason is None:
            console.log_event("Homing routine finished.", level=LogLevel.INFO, source="CMD")
        else:
            console.log_event(f"Homing routine aborted: {reason}", level=LogLevel.ERROR, source="CMD")

    def _run(self, steps: List[HomingStep]) -> Optional[str]:
        """Every step in order; the reason it stopped, or ``None``."""
        stat = get_stat_channel()  # per-thread channel (channel_stat.py)
        if stat is None:
            return "LinuxCNC is not running."
        console = get_console_logger()
        console.log_event(f"Running the homing routine ({len(steps)} step(s)).", level=LogLevel.INFO, source="CMD")
        for step in steps:
            if step.kind == "home":
                reason = self._home(stat, step)
            else:
                reason = self._mdi(stat, step.line)
            if reason is not None:
                return f"{step.line!r}: {reason}"
        execute_sync_cmd("mode", 1.0, _MODE_MANUAL)
        return None

    def _mdi(self, stat: Any, line: str) -> Optional[str]:
        try:
            serial = dispatch_mdi(line)
        except Exception as exc:  # noqa: BLE001 - LinuxCNC refused the line
            return f"LinuxCNC refused it ({exc})."
        return MacroExecutionService._wait_until_idle(stat, serial)

    def _home(self, stat: Any, step: HomingStep) -> Optional[str]:
        if not step.axes:
            targets = [(-1, self._all_joints())]
        else:
            targets = []
            for letter in step.axes:
                joints = self._axis_joints(letter)
                if not joints:
                    return f"this machine has no axis {letter}."
                targets.append((joints[0], joints))
        for command_joint, joints in targets:
            execute_sync_cmd("mode", 1.0, _MODE_MANUAL)
            execute_sync_cmd("teleop_enable", 1.0, 0)
            execute_sync_cmd("home", 1.0, command_joint)
            reason = self._wait_homed(stat, joints)
            if reason is not None:
                return reason
        return None

    @staticmethod
    def _wait_homed(stat: Any, joints: List[int], timeout: float = HOME_TIMEOUT_S) -> Optional[str]:
        """Block until every joint in ``joints`` is homed; the reason it
        failed otherwise."""
        start = time.monotonic()
        started = False
        while True:
            stat.poll()
            if stat.estop:
                return "machine entered E-Stop while homing."
            if stat.task_state != MachineState.ON.value:
                return "machine was turned off while homing."
            homed = list(getattr(stat, "homed", ()) or ())
            if all(j < len(homed) and homed[j] for j in joints):
                return None
            joint_info = getattr(stat, "joint", None)
            if joint_info is not None:
                homing = any(
                    j < len(joint_info) and joint_info[j].get("homing") for j in joints
                )
                elapsed = time.monotonic() - start
                if homing:
                    started = True
                elif started or elapsed > HOME_START_GRACE_S:
                    return (
                        f"joint(s) {', '.join(map(str, joints))} stopped homing without being "
                        "homed (home switch not reached? see LinuxCNC's error message)."
                    )
            if time.monotonic() - start > timeout:
                return f"joint(s) {', '.join(map(str, joints))} not homed after {timeout:.0f} s."
            time.sleep(_POLL_S)

    # -- program guard ---------------------------------------------------- #

    def require_homed(self) -> None:
        """Refuse to run a program on a machine with a homing routine
        until every joint is homed — ``NO_FORCE_HOMING = 1`` means
        LinuxCNC no longer refuses it itself."""
        if self.override() is None:
            return
        stat = get_stat_channel()
        if stat is None:
            return
        stat.poll()
        homed = list(getattr(stat, "homed", ()) or ())
        missing = [j for j in self._all_joints() if not (j < len(homed) and homed[j])]
        if missing:
            raise ConflictError(
                f"Home the machine first (joint(s) {', '.join(map(str, missing))} not homed)."
            )


_SERVICE: Optional[HomingRoutineService] = None


def get_homing_routine_service() -> HomingRoutineService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = HomingRoutineService()
    return _SERVICE


__all__ = ["HomingRoutineService", "get_homing_routine_service"]
