"""What a converted print asks to run before it starts
(`.agent/component/gcode_upload.md` § 1, ``; LINUXCNC_UI_PRESTART:``).

A slicer's start G-code homes (``G28``) and levels (``G29``); neither can
run inside a LinuxCNC program (homing needs MANUAL mode, probing MDI).
The upload moves them into the file's header line, and "Run" does them
here, in order, on a worker thread, before the program starts:

* ``home`` — the machine's ``[homing_override]`` routine, or every joint
  by ``HOME_SEQUENCE`` (``HomingRoutineService.run_blocking``);
* ``level`` — ``Z_TILT_ADJUST`` when the machine has ``[z_tilt]``
  (skipped with a console note otherwise);

then ``AUTO_RUN``. The first failure stops it before the program starts,
logged in the console.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import List, Optional

from core.gcode_converter import read_prestart
from exceptions import BaseAPIException, ConflictError
from hardware import get_stat_channel, linuxcnc
from hardware.Connection import execute_sync_cmd
from services.ConsoleLogger import LogLevel, get_console_logger

logger = logging.getLogger("backend.services.PrintStartService")

#: Enough of the file's start for the header line.
HEAD_BYTES = 4096


def prestart_steps(path: str) -> List[str]:
    """The steps the loaded file's header asks for, ``[]`` for none."""
    try:
        with Path(path).open("rb") as fp:
            return read_prestart(fp.read(HEAD_BYTES).decode("utf-8", errors="ignore"))
    except OSError:
        return []


class PrintStartService:
    def __init__(self) -> None:
        self._worker: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def is_running(self) -> bool:
        worker = self._worker
        return worker is not None and worker.is_alive()

    def join(self, timeout: Optional[float] = None) -> None:
        worker = self._worker
        if worker is not None:
            worker.join(timeout)

    def start(self, steps: List[str], line_number: int = 0) -> None:
        from services.HomingRoutineService import get_homing_routine_service
        from services.MacroExecutionService import get_macro_execution_service

        if get_macro_execution_service().is_running() or get_homing_routine_service().is_running():
            raise ConflictError("A macro or the homing routine is running.")
        with self._lock:
            if self.is_running():
                raise ConflictError("The print is already being prepared.")
            self._worker = threading.Thread(
                target=self._run, args=(list(steps), line_number), name="print-start", daemon=True
            )
            self._worker.start()

    def _run(self, steps: List[str], line_number: int) -> None:
        console = get_console_logger()
        try:
            reason = self._prepare(steps)
        except Exception as exc:  # noqa: BLE001 - report, don't die silently
            logger.exception("Print start crashed: %s", exc)
            reason = str(exc)
        if reason is not None:
            console.log_event(f"Print not started: {reason}", level=LogLevel.ERROR, source="CMD")
            return
        try:
            from services.HomingRoutineService import get_homing_routine_service

            get_homing_routine_service().require_homed()
            execute_sync_cmd("mode", 3, getattr(linuxcnc, "MODE_AUTO", 2))
            execute_sync_cmd("auto", 0, getattr(linuxcnc, "AUTO_RUN", 0), line_number)
        except BaseAPIException as exc:
            console.log_event(f"Print not started: {exc.detail}", level=LogLevel.ERROR, source="CMD")
        except Exception as exc:  # noqa: BLE001
            console.log_event(f"Print not started: {exc}", level=LogLevel.ERROR, source="CMD")

    @staticmethod
    def _prepare(steps: List[str]) -> Optional[str]:
        from services.HomingRoutineService import get_homing_routine_service
        from services.ZTiltService import ZTiltError, get_z_tilt_service

        console = get_console_logger()
        stat = get_stat_channel()
        if stat is None:
            return "LinuxCNC is not running."
        if "home" in steps:
            console.log_event("Print start: homing (the file's G28).", level=LogLevel.INFO, source="CMD")
            reason = get_homing_routine_service().run_blocking(stat)
            if reason is not None:
                return f"homing: {reason}"
        if "level" in steps:
            z_tilt = get_z_tilt_service()
            if z_tilt.settings() is None:
                console.log_event(
                    "Print start: the file's G29 skipped — this machine has no [z_tilt].",
                    level=LogLevel.WARNING, source="CMD",
                )
            else:
                console.log_event("Print start: Z_TILT_ADJUST (the file's G29).", level=LogLevel.INFO, source="CMD")
                try:
                    z_tilt.run(stat)
                except ZTiltError as exc:
                    return f"Z_TILT_ADJUST: {exc}"
                except BaseAPIException as exc:
                    return f"Z_TILT_ADJUST: {exc.detail}"
        return None


_SERVICE: Optional[PrintStartService] = None


def get_print_start_service() -> PrintStartService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = PrintStartService()
    return _SERVICE


__all__ = ["PrintStartService", "get_print_start_service", "prestart_steps"]
