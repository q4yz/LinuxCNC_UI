"""Program module service — :class:`ProgramService` + :class:`ProgramProgressResponse`.

This is the canonical home for the program-lifecycle facade that
used to live on ``backend.services.machine_service.MachineControlService`.
The HTTP edge (``backend/modules/program/router.py``) is a thin
wrapper around :func:`get_program_lifecycle_service`; this module
owns the G-code program lifecycle (load / unload / start / stop /
pause / resume / progress).

The :class:`ProgramProgressResponse` Pydantic model moved here from
``services.machine_service`` because it is part of the same
program-lifecycle surface; the base-thread snapshot router
(``routers/base_thread.py``) imports it from
``modules.program.service``.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from hardware import connection
from hardware.connection import execute_sync_cmd, linuxcnc
from pydantic import BaseModel, Field

from services.line_count_cache import lookup as lookup_line_count

logger = logging.getLogger("backend.modules.program.service")


class ProgramProgressResponse(BaseModel):
    """Progress snapshot for the active G-code program.

    Returned by ``GET /api/v1/modules/program/progress`` so the dashboard
    can poll once a second without saturating NML. ``total_lines``
    comes from a backend-side line-count cache populated when the
    file is loaded; ``current_line`` and ``motion_line`` come
    straight from ``linuxcnc.stat``. ``interp_state`` mirrors the
    raw integer so the widget can decide whether to keep polling.
    """

    current_line: int = Field(
        ...,
        ge=0,
        description=(
            "Line the RS274NGC interpreter is currently reading. "
            "Mirrors ``stat.current_line``."
        ),
    )
    motion_line: int = Field(
        ...,
        ge=0,
        description=(
            "Source line motion is currently executing. Mirrors "
            "``stat.motion_line``; ``0`` when the interpreter is idle."
        ),
    )
    total_lines: int = Field(
        ...,
        ge=0,
        description=(
            "Total line count of the loaded G-code file, populated "
            "from a backend-side cache at ``program_open`` time. "
            "``0`` when no file is loaded or the file was unreadable."
        ),
    )
    file: str = Field(
        ...,
        description=(
            "Absolute path of the loaded G-code file (``stat.file``) "
            "or empty string when nothing is loaded."
        ),
    )
    interp_state: int = Field(
        ...,
        description=(
            "Current ``linuxcnc.INTERP_*`` state. ``1`` IDLE, "
            "``2`` READING, ``3`` PAUSED, ``4`` WAITING."
        ),
    )


class ProgramService:
    """G-code program lifecycle facade.

    Owns the canonical two-step program lifecycle:

    1. ``load_program`` calls ``command.program_open(path)`` which
       sets ``stat.file`` while leaving ``interp_state`` at
       ``INTERP_IDLE``. ``program_open`` is asynchronous on real
       LinuxCNC — the service polls ``stat.file`` until it matches
       the requested path, raising ``TimeoutError`` if the load
       does not land within :attr:`LOAD_TIMEOUT_S`.
    2. ``start_program`` calls ``auto(AUTO_RUN, line)`` which flips
       ``interp_state`` to ``INTERP_READING``. The endpoint refuses
       with ``RuntimeError`` when no file has been loaded.
    """

    LOAD_TIMEOUT_S = 5.0

    def _is_program_loaded(self) -> bool:
        """Helper to safely check if the interpreter has a file loaded."""
        stat = connection.get_machine_stat()
        if not stat:
            return False
        if hasattr(stat, 'poll'):
            stat.poll()
        return bool(getattr(stat, "file", ""))

    def _await_load(self, target_path: str) -> None:
        """Polls LinuxCNC memory until the file pointer matches the target."""
        deadline = time.monotonic() + self.LOAD_TIMEOUT_S
        while True:
            stat = connection.get_machine_stat()
            if stat:
                if hasattr(stat, 'poll'):
                    stat.poll()
                current = str(getattr(stat, "file", "") or "")
                if current == target_path:
                    return

            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"LinuxCNC did not load '{target_path}' within {self.LOAD_TIMEOUT_S}s"
                )
            time.sleep(0.05)

    def load_program(self, file_path: str) -> None:
        execute_sync_cmd("program_open", self.LOAD_TIMEOUT_S, file_path)
        self._await_load(file_path)

    def unload_program(self) -> None:
        execute_sync_cmd("program_open", self.LOAD_TIMEOUT_S, "")

    def start_program(self, line_number: int = 0) -> None:
        if not self._is_program_loaded():
            raise RuntimeError("No program loaded. Load a file before starting.")

        execute_sync_cmd("mode", 3, getattr(linuxcnc, "MODE_AUTO", 2))
        execute_sync_cmd("auto", 0, getattr(linuxcnc, "AUTO_RUN", 0), line_number)

    def stop_program(self) -> None:
        execute_sync_cmd("abort")

    def pause_program(self) -> None:
        execute_sync_cmd("auto", 0, getattr(linuxcnc, "AUTO_PAUSE", 1))

    def resume_program(self) -> None:
        execute_sync_cmd("auto", 0, getattr(linuxcnc, "AUTO_RESUME", 2))

    def progress_program(self, stat=None) -> ProgramProgressResponse:
        stat = connection.get_machine_stat()

        if stat is None:
            return ProgramProgressResponse(
                current_line=0,
                motion_line=0,
                total_lines=0,
                file="",
                interp_state=int(getattr(linuxcnc, "INTERP_IDLE", 1)),
            )

        poll = getattr(stat, "poll", None)
        if callable(poll):
            poll()

        file_path = str(getattr(stat, "file", "") or "")
        current_line = int(getattr(stat, "current_line", 0) or 0)
        motion_line = int(getattr(stat, "motion_line", 0) or 0)
        interp_state = int(
            getattr(stat, "interp_state", getattr(linuxcnc, "INTERP_IDLE", 1))
            or getattr(linuxcnc, "INTERP_IDLE", 1)
        )

        return ProgramProgressResponse(
            current_line=max(0, current_line),
            motion_line=max(0, motion_line),
            total_lines=max(0, lookup_line_count(file_path)),
            file=file_path,
            interp_state=interp_state,
        )


_program_lifecycle_service: Optional[ProgramService] = None


def get_program_lifecycle_service() -> ProgramService:
    """Lazy module-level singleton (program lifecycle facade).

    Named ``get_program_lifecycle_service`` (not ``get_program_service``)
    to avoid collision with
    :func:`services.domain_file_services.get_program_service` — the
    filesystem-level ``ProgramFileService`` already owns that name.
    """
    global _program_lifecycle_service
    if _program_lifecycle_service is None:
        _program_lifecycle_service = ProgramService()
    return _program_lifecycle_service


__all__ = [
    "ProgramProgressResponse",
    "ProgramService",
    "get_program_lifecycle_service",
]