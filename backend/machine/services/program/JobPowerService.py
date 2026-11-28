"""A job that switches the machine on for itself and off when it ends
(``POST /api/v1/modules/program/run_powered``; the slicer's "Upload and
print" with Settings -> Slicer -> *Power on for the job*).

``run_powered``:

1. releases the E-stop (``StateService.reset_estop``, with its retries
   for the MCU link) and switches the machine on, when it is not on;
2. starts the loaded program like the Start button
   (``ProgramService.start_program``: a converted print's G28 / G29 run
   first);
3. watches the job on a worker: once it ran and the machine has been
   idle for :attr:`END_SETTLE_S` (finished, stopped or failed), the
   machine is switched off again.

A job that does not start switches the machine off again at once, when
this call switched it on. An E-stop during the job leaves the machine in
E-stop: nothing to switch off. Only the latest job is watched.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

from hardware.Connection import execute_sync_cmd, get_stat_channel, linuxcnc
from services.machine.ConsoleLogger import LogLevel, get_console_logger

logger = logging.getLogger("backend.services.program.JobPowerService")


def _const(name: str, default: int) -> int:
    return int(getattr(linuxcnc, name, default))


def _poll():
    stat = get_stat_channel()
    if stat is not None and callable(getattr(stat, "poll", None)):
        stat.poll()
    return stat


def _task_state() -> Optional[int]:
    stat = _poll()
    value = getattr(stat, "task_state", None) if stat is not None else None
    return int(value) if value is not None else None


def _busy() -> bool:
    """A program, or a print's G28 / G29 before it, is running (or paused)."""
    from services.program.PrintStartService import get_print_start_service

    if get_print_start_service().is_running():
        return True
    stat = _poll()
    if stat is None:
        return False
    idle = _const("INTERP_IDLE", 1)
    return int(getattr(stat, "interp_state", idle) or idle) != idle


def _console(text: str, level: LogLevel = LogLevel.INFO) -> None:
    try:
        get_console_logger().log_event(text, level=level, source="CMD")
    except Exception:  # noqa: BLE001 - the console is best effort
        logger.info(text)


class JobPowerService:
    POWER_ON_TIMEOUT_S = 5.0
    #: The job has to show up as running within this time, else it ended.
    START_SEEN_TIMEOUT_S = 30.0
    #: Idle this long = ended (a print's G28 / G29 and the program follow
    #: one another with short idle gaps).
    END_SETTLE_S = 2.0
    POLL_S = 0.25

    def __init__(self, busy: Callable[[], bool] = _busy, task_state: Callable[[], Optional[int]] = _task_state) -> None:
        self._busy = busy
        self._task_state = task_state
        self._lock = threading.Lock()
        self._generation = 0
        self._watcher: Optional[threading.Thread] = None

    # -- power -------------------------------------------------------------

    def _power_on(self) -> bool:
        """Leave E-stop and switch on; ``True`` when this changed anything."""
        on = _const("STATE_ON", 4)
        state = self._task_state()
        if state == on:
            return False
        if state == _const("STATE_ESTOP", 1):
            from services.machine.StateService import get_state_service

            get_state_service().reset_estop()  # ConflictError when it does not hold
        execute_sync_cmd("state", 3.0, on)
        deadline = time.monotonic() + self.POWER_ON_TIMEOUT_S
        while self._task_state() != on:
            if time.monotonic() >= deadline:
                from exceptions import ConflictError

                raise ConflictError("The machine did not switch on (check the E-stop and the MCU link).")
            time.sleep(0.05)
        _console("Job: E-stop released, machine on")
        return True

    def _power_off(self, why: str) -> None:
        if self._task_state() != _const("STATE_ON", 4):
            return  # already off or in E-stop
        try:
            execute_sync_cmd("state", 3.0, _const("STATE_OFF", 3))
            _console(f"Job {why}: machine off")
        except Exception as exc:  # noqa: BLE001
            _console(f"Job {why}, but the machine did not switch off: {exc}", LogLevel.ERROR)

    # -- the job -----------------------------------------------------------

    def run_powered(self, line_number: int = 0) -> None:
        from services.program.ProgramService import get_program_lifecycle_service

        switched_on = self._power_on()
        try:
            get_program_lifecycle_service().start_program(line_number)
        except Exception:
            if switched_on:
                self._power_off("did not start")
            raise
        self._watch()

    def _watch(self) -> None:
        with self._lock:
            self._generation += 1
            generation = self._generation
            self._watcher = threading.Thread(target=self._run, args=(generation,), name="job-power", daemon=True)
            self._watcher.start()

    def join(self, timeout: Optional[float] = None) -> None:
        watcher = self._watcher
        if watcher is not None:
            watcher.join(timeout)

    def _current(self, generation: int) -> bool:
        return generation == self._generation

    def _run(self, generation: int) -> None:
        # 1. the job shows up
        deadline = time.monotonic() + self.START_SEEN_TIMEOUT_S
        while not self._busy():
            if not self._current(generation):
                return
            if time.monotonic() >= deadline:
                break
            time.sleep(self.POLL_S)
        # 2. it ends: idle for END_SETTLE_S
        idle_since: Optional[float] = None
        while self._current(generation):
            if self._busy():
                idle_since = None
            elif idle_since is None:
                idle_since = time.monotonic()
            elif time.monotonic() - idle_since >= self.END_SETTLE_S:
                self._power_off("ended")
                return
            time.sleep(self.POLL_S)


_service: Optional[JobPowerService] = None


def get_job_power_service() -> JobPowerService:
    global _service
    if _service is None:
        _service = JobPowerService()
    return _service
