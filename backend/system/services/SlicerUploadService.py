"""G-code sent by a slicer over the network (``routers/octoprint.py``).

Stores the file under ``nc_files/`` like the UI's own upload and, when
the slicer asks for it (OctoPrint's ``select`` / ``print``), loads it
into LinuxCNC through the machine backend.

``print`` (the slicer's "Upload and print") also **starts** it — only
when the operator switched that on (UI setting ``slicer.allow_start``,
Settings -> Slicer; off by default: a network upload then never sets the
machine in motion). The start is the Start button's: the machine
backend's ``program/run``, so the file's G28 / G29 run first and an
unhomed, switched-off or busy machine refuses.

With ``slicer.power_cycle`` on as well (Settings -> Slicer) the start is
``program/run_powered``: the E-stop is released and the machine switched
on for the job, and switched off once the job ended.

The calls to the machine backend carry the slicer's API key (a login's
token): the machine backend checks the caller like any other.
"""
from __future__ import annotations

import json
import logging
import urllib.request
from functools import lru_cache
from typing import Any, Optional

from domain_file_services import ProgramFileService, get_program_service
from services.MachineLifecycleService import linuxcnc_pids

logger = logging.getLogger("backend.system.slicer_upload")

#: The machine backend (runs with the LinuxCNC session) and its load route.
MACHINE_BACKEND = "http://127.0.0.1:8000"
LOAD_ROUTE = "/api/v1/modules/program/load"
RUN_ROUTE = "/api/v1/modules/program/run"
RUN_POWERED_ROUTE = "/api/v1/modules/program/run_powered"
LOAD_TIMEOUT_S = 10
#: UI setting (Settings -> Slicer): the slicer's "print" starts the file.
ALLOW_START_KEY = "slicer.allow_start"
#: UI setting: the slicer's start releases the E-stop and powers on, off when done.
POWER_CYCLE_KEY = "slicer.power_cycle"


class UnsupportedFileError(ValueError):
    """Not a G-code file LinuxCNC runs (``ProgramFileService.ALLOWED_EXTENSIONS``)."""


class SlicerUploadService:
    def __init__(self, programs: ProgramFileService, machine_backend: str = MACHINE_BACKEND) -> None:
        self._programs = programs
        self._machine_backend = machine_backend

    def machine_running(self) -> bool:
        return bool(linuxcnc_pids())

    def save(self, filename: str, directory: str, data: bytes) -> str:
        """Store ``data`` as ``directory/filename`` (overwriting, as
        OctoPrint does) and return that path relative to ``nc_files/``.
        Only the file's own name counts; ``safe_join`` rejects ``..``."""
        name = self._programs.safe_join(filename or "").name
        if not name:
            raise ValueError("empty filename")
        if not ProgramFileService.gcode_filter(name):
            allowed = ", ".join(ProgramFileService.ALLOWED_EXTENSIONS)
            raise UnsupportedFileError(f"{name}: only {allowed} files can be sent")
        path = "/".join(p for p in (directory.strip("/"), name) if p)
        self._programs.safe_join(path)
        path = self._programs.save_upload(path, data)
        logger.info("Slicer upload stored: %s (%d bytes)", path, len(data))
        return path

    def load(self, path: str, token: str = "") -> bool:
        """Load ``path`` into LinuxCNC; ``False`` when LinuxCNC is not
        running or the machine backend refuses (e.g. a program runs)."""
        if not self.machine_running():
            logger.info("Slicer asked to load %s, but LinuxCNC is not running", path)
            return False
        if self._post(LOAD_ROUTE, {"filename": path}, f"load slicer upload {path}", token):
            logger.info("Slicer upload loaded into LinuxCNC: %s", path)
            return True
        return False

    @staticmethod
    def _setting_on(key: str) -> bool:
        from services.UiSettingsService import get_ui_settings_service

        try:
            return get_ui_settings_service().read(key) is True
        except Exception:  # noqa: BLE001 - unset (404) or unreadable: off
            return False

    def start_allowed(self) -> bool:
        """The operator let the slicer start prints (``slicer.allow_start``)."""
        return self._setting_on(ALLOW_START_KEY)

    def power_cycle(self) -> bool:
        """The slicer's start powers the machine on and off (``slicer.power_cycle``)."""
        return self._setting_on(POWER_CYCLE_KEY)

    def start(self, path: str, token: str = "") -> tuple[bool, bool]:
        """Load ``path`` and start it like the Start button; ``(loaded,
        started)``. The machine backend refuses a start it cannot do
        (machine off, not homed, a program or routine running)."""
        if not self.load(path, token):
            return False, False
        route = RUN_POWERED_ROUTE if self.power_cycle() else RUN_ROUTE
        if self._post(route, None, f"start slicer upload {path}", token):
            logger.info("Slicer upload started: %s", path)
            return True, True
        return True, False

    def _post(self, route: str, body: Optional[dict[str, Any]], what: str, token: str = "") -> bool:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(
            self._machine_backend + route,
            data=json.dumps(body).encode("utf-8") if body is not None else b"",
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=LOAD_TIMEOUT_S):
                return True
        except OSError as exc:  # URLError / HTTPError (409 while a program runs, ...)
            logger.warning("Could not %s: %s", what, exc)
            return False


@lru_cache(maxsize=1)
def get_slicer_upload_service() -> SlicerUploadService:
    return SlicerUploadService(get_program_service())


__all__ = ["SlicerUploadService", "UnsupportedFileError", "get_slicer_upload_service"]
