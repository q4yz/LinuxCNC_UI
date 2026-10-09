"""System update — launch ``scripts/update.sh`` and report its progress.

The script stops and restarts this very service, so the service cannot
know when the update is finished. The script records every step in
``UPDATE_STATUS_FILE`` (through ``scripts/update_status.py``) and the
UI polls :meth:`UpdateService.status`; ``done`` is written only after
the restarted services answered.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from domain_file_services.paths import (
    PROJECT_ROOT,
    UPDATE_LOG_FILE,
    UPDATE_SCRIPT,
    UPDATE_STATUS_FILE,
)
from exceptions import ConflictError
from models.UpdateModels import UpdateStatusResponse

logger = logging.getLogger("backend.services.UpdateService")

STATUS_SCRIPT = PROJECT_ROOT / "scripts" / "update_status.py"

#: A "running" status older than this (no progress write) is treated as
#: a dead run — a new update may start, and the UI stops waiting.
STALE_AFTER = timedelta(minutes=30)


class UpdateLaunchError(RuntimeError):
    """The update script could not be started."""


class UpdateService:
    def __init__(
        self,
        status_file: Path = UPDATE_STATUS_FILE,
        script: Path = UPDATE_SCRIPT,
        log_file: Path = UPDATE_LOG_FILE,
    ) -> None:
        self._status_file = status_file
        self._script = script
        self._log_file = log_file

    # -- status ---------------------------------------------------------- #

    def status(self) -> UpdateStatusResponse:
        """The last run's progress; ``idle`` when no update ever ran."""
        raw = self._read()
        if raw is None:
            return UpdateStatusResponse(state="idle")
        try:
            status = UpdateStatusResponse.model_validate(raw)
        except ValueError:
            logger.warning("Ignoring malformed update status in %s", self._status_file)
            return UpdateStatusResponse(state="idle")
        if status.state == "running" and self._is_stale(status):
            return status.model_copy(update={
                "state": "failed",
                "message": f"No progress since {status.updated_at} — the update process died.",
            })
        return status

    # -- start ----------------------------------------------------------- #

    def start(self) -> str:
        """Launch the update detached; returns its run id."""
        current = self.status()
        if current.state == "running":
            raise ConflictError(f"An update is already running (phase: {current.phase or 'starting'})")
        if not self._script.exists():
            raise UpdateLaunchError(f"Update script not found at {self._script}")

        run_id = uuid.uuid4().hex[:12]
        env = {
            **os.environ,
            "UPDATE_RUN_ID": run_id,
            "UPDATE_STATUS_FILE": str(self._status_file),
        }
        # Recorded before launching, so the very first poll already
        # sees this run (and never an older run's "done").
        self._write_status(env, "running", "starting")
        try:
            self._launch(env)
        except Exception as exc:  # noqa: BLE001
            self._write_status(env, "failed", "starting", f"Could not start the update: {exc}")
            raise UpdateLaunchError(str(exc)) from exc
        logger.info("Update %s launched detached; output appending to %s", run_id, self._log_file)
        return run_id

    def _launch(self, env: dict[str, str]) -> None:
        """Detach ``update.sh`` from this Uvicorn process.

        The script stops and restarts linuxcnc-ui-system — the service
        serving this request — so it must not run inside our session /
        process group and must not be awaited. ``start_new_session``
        makes it its own process leader, and with ``KillMode=process``
        in the unit file systemd signals only the main Uvicorn PID, so
        the script survives the restart.
        """
        popen_kwargs: dict[str, Any] = {}
        if sys.platform != "win32":
            popen_kwargs["start_new_session"] = True
        with self._log_file.open("ab") as log_file:
            subprocess.Popen(
                ["bash", str(self._script)],
                cwd=str(PROJECT_ROOT),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                **popen_kwargs,
            )

    def _write_status(self, env: dict[str, str], state: str, phase: str, message: str = "") -> None:
        """Same writer the script uses, so there is one status format."""
        try:
            subprocess.run(
                [sys.executable, str(STATUS_SCRIPT), state, phase, message],
                env=env, check=True, timeout=15, capture_output=True,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("Could not write update status: %s", exc)

    # -- helpers --------------------------------------------------------- #

    def _read(self) -> Optional[dict[str, Any]]:
        try:
            data = json.loads(self._status_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            logger.warning("Unreadable update status %s: %s", self._status_file, exc)
            return None
        return data if isinstance(data, dict) else None

    @staticmethod
    def _is_stale(status: UpdateStatusResponse) -> bool:
        if not status.updated_at:
            return False
        try:
            updated = datetime.fromisoformat(status.updated_at)
        except ValueError:
            return False
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - updated > STALE_AFTER


_SERVICE_INSTANCE: Optional[UpdateService] = None


def get_update_service() -> UpdateService:
    global _SERVICE_INSTANCE
    if _SERVICE_INSTANCE is None:
        _SERVICE_INSTANCE = UpdateService()
    return _SERVICE_INSTANCE


def set_update_service(service: Optional[UpdateService]) -> None:
    global _SERVICE_INSTANCE
    _SERVICE_INSTANCE = service


__all__ = [
    "UpdateLaunchError",
    "UpdateService",
    "get_update_service",
    "set_update_service",
]
