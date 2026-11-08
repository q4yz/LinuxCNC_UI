"""G-code sent by a slicer over the network (``routers/octoprint.py``).

Stores the file under ``nc_files/`` like the UI's own upload and, when
the slicer asks for it (OctoPrint's ``select`` / ``print``), loads it
into LinuxCNC through the machine backend. It is never started: a
network upload must not set a machine in motion — the operator starts
it at the machine.
"""
from __future__ import annotations

import json
import logging
import urllib.request
from functools import lru_cache

from domain_file_services import ProgramFileService, get_program_service
from services.MachineLifecycleService import linuxcnc_pids

logger = logging.getLogger("backend.system.slicer_upload")

#: The machine backend (runs with the LinuxCNC session) and its load route.
MACHINE_BACKEND = "http://127.0.0.1:8000"
LOAD_ROUTE = "/api/v1/modules/program/load"
LOAD_TIMEOUT_S = 10


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

    def load(self, path: str) -> bool:
        """Load ``path`` into LinuxCNC; ``False`` when LinuxCNC is not
        running or the machine backend refuses (e.g. a program runs)."""
        if not self.machine_running():
            logger.info("Slicer asked to load %s, but LinuxCNC is not running", path)
            return False
        request = urllib.request.Request(
            self._machine_backend + LOAD_ROUTE,
            data=json.dumps({"filename": path}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=LOAD_TIMEOUT_S):
                logger.info("Slicer upload loaded into LinuxCNC: %s", path)
                return True
        except OSError as exc:  # URLError / HTTPError (409 while a program runs, ...)
            logger.warning("Could not load slicer upload %s: %s", path, exc)
            return False


@lru_cache(maxsize=1)
def get_slicer_upload_service() -> SlicerUploadService:
    return SlicerUploadService(get_program_service())


__all__ = ["SlicerUploadService", "UnsupportedFileError", "get_slicer_upload_service"]
