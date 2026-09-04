"""Machine process lifecycle — the system service's process supervisor.

The system service is the always-running half of the backend split,
so it owns the LinuxCNC *process* lifecycle: detecting whether a
``linuxcnc`` session is alive, starting the generated INI, stopping
the session again, and switching the active machine (compile →
deploy → restart).

Starting literally runs the console command::

    linuxcnc <machine_config/active/machine.ini>

The process is spawned detached (``start_new_session=True``) with its
console output tee'd into ``logs/linuxcnc_console.log`` at the
repository root and ``DISPLAY`` inherited (defaulting to ``:0`` so the
LinuxCNC GUI opens on the machine's console display). The launch
command can be overridden with the ``LINUXCNC_START_COMMAND`` env var
using a ``{ini}`` placeholder, e.g. ``"xterm -e linuxcnc {ini}"``.
"""
from __future__ import annotations

import logging
import os
import shlex
import signal
import subprocess
import time
from pathlib import Path
from typing import List, Optional

from exceptions import BadRequestError, ConflictError, NotFoundError

from domain_file_services import (
    get_active_service,
    get_config_service,
    get_staged_service,
)
from domain_file_services.paths import ACTIVE_DIR

logger = logging.getLogger("backend.system.machine_lifecycle")

#: LinuxCNC session process names — mirrors the guard in
#: ``scripts/update.sh`` (linuxcnc/emc) plus the background daemons a
#: session spawns (milltask, linuxcncsvr).
PROCESS_PATTERNS: tuple[str, ...] = ("linuxcnc", "emc", "milltask", "linuxcncsvr")

#: Console log for started LinuxCNC sessions (repository root).
_REPO_ROOT = Path(__file__).resolve().parents[3]
_CONSOLE_LOG = _REPO_ROOT / "logs" / "linuxcnc_console.log"

#: Grace period (seconds) between SIGINT and SIGTERM / SIGKILL escalation.
_STOP_GRACE_SECONDS = 10.0


def linuxcnc_pids() -> List[int]:
    """Return the pids of every live LinuxCNC session process.

    ``pgrep -x <name>`` is used because it needs no privileges and
    survives PID recycling. When ``pgrep`` is unavailable (non-Linux
    dev machine) the probe reports "not running" instead of failing.
    """
    pids: List[int] = []
    for name in PROCESS_PATTERNS:
        try:
            result = subprocess.run(
                ["pgrep", "-x", name],
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            continue
        if result.returncode == 0:
            pids.extend(int(line) for line in result.stdout.split() if line.isdigit())
    return sorted(set(pids))


class MachineLifecycleService:
    """Start / stop / switch the LinuxCNC machine session."""

    # ------------------------------------------------------------------ #
    # Introspection                                                       #
    # ------------------------------------------------------------------ #

    def is_running(self) -> bool:
        return bool(linuxcnc_pids())

    def active_ini(self) -> Optional[Path]:
        """First ``*.ini`` under ``machine_config/active`` (the generated one)."""
        if not ACTIVE_DIR.exists():
            return None
        inis = sorted(ACTIVE_DIR.glob("*.ini"))
        return inis[0] if inis else None

    def machine_name(self) -> Optional[str]:
        try:
            return get_active_service().machine_name()
        except Exception as exc:  # noqa: BLE001 - best-effort probe
            logger.warning("machine_name probe failed: %s", exc)
            return None

    def status(self) -> dict:
        ini = self.active_ini()
        return {
            "running": self.is_running(),
            "pids": linuxcnc_pids(),
            "machine_name": self.machine_name(),
            "ini_path": str(ini) if ini else None,
            "ini_exists": ini is not None,
        }

    # ------------------------------------------------------------------ #
    # Start                                                               #
    # ------------------------------------------------------------------ #

    def start(self) -> dict:
        """Run ``linuxcnc <generated ini>`` as a console process."""
        if self.is_running():
            raise ConflictError(
                f"LinuxCNC is already running (pids {linuxcnc_pids()})."
            )

        ini = self.active_ini()
        if ini is None:
            raise NotFoundError(
                "No generated INI found in machine_config/active — "
                "compile and deploy a machine first."
            )

        command = self._build_command(ini)
        env = os.environ.copy()
        # LinuxCNC opens its GUI on the console display; a systemd
        # service has no DISPLAY of its own, so default to :0.
        env.setdefault("DISPLAY", ":0")

        _CONSOLE_LOG.parent.mkdir(parents=True, exist_ok=True)
        try:
            log_handle = open(_CONSOLE_LOG, "a", buffering=1, encoding="utf-8")
        except OSError as exc:  # pragma: no cover - unwritable repo root
            raise BadRequestError(f"Cannot open console log {_CONSOLE_LOG}: {exc}") from exc

        try:
            process = subprocess.Popen(
                command,
                cwd=str(ACTIVE_DIR),
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                env=env,
                start_new_session=True,
            )
        except FileNotFoundError as exc:
            log_handle.close()
            raise NotFoundError(
                f"Cannot start LinuxCNC: {command[0]!r} executable not found."
            ) from exc
        except OSError as exc:
            log_handle.close()
            raise BadRequestError(f"Cannot start LinuxCNC: {exc}") from exc

        logger.info(
            "Started LinuxCNC session (pid %s): %s (console log: %s)",
            process.pid,
            " ".join(command),
            _CONSOLE_LOG,
        )

        # Give the launcher a beat so an immediate crash (missing INI
        # section, realtime error, …) surfaces as an error instead of
        # a phantom "running" status.
        time.sleep(0.5)
        if process.poll() is not None:
            raise BadRequestError(
                f"LinuxCNC exited immediately (code {process.returncode}). "
                f"See {_CONSOLE_LOG} for the console output."
            )

        status = self.status()
        status["started_pid"] = process.pid
        return status

    def _build_command(self, ini: Path) -> List[str]:
        """Resolve the launch command (``LINUXCNC_START_COMMAND`` override)."""
        template = os.environ.get("LINUXCNC_START_COMMAND", "").strip()
        if not template:
            return ["linuxcnc", str(ini)]
        return shlex.split(template.format(ini=str(ini)))

    # ------------------------------------------------------------------ #
    # Stop                                                                #
    # ------------------------------------------------------------------ #

    def stop(self, grace_seconds: float = _STOP_GRACE_SECONDS) -> dict:
        """Stop the running LinuxCNC session (SIGINT → SIGTERM → SIGKILL)."""
        pids = linuxcnc_pids()
        if not pids:
            return self.status()

        self._signal_all(pids, signal.SIGINT)
        if self._wait_for_exit(grace_seconds):
            logger.info("LinuxCNC stopped after SIGINT.")
            return self.status()

        pids = linuxcnc_pids()
        if pids and hasattr(signal, "SIGTERM"):
            self._signal_all(pids, signal.SIGTERM)
            if self._wait_for_exit(grace_seconds):
                logger.info("LinuxCNC stopped after SIGTERM.")
                return self.status()

        pids = linuxcnc_pids()
        if pids and hasattr(signal, "SIGKILL"):
            logger.warning("LinuxCNC did not exit — escalating to SIGKILL.")
            self._signal_all(pids, signal.SIGKILL)
            self._wait_for_exit(2.0)

        if linuxcnc_pids():
            raise ConflictError(
                f"LinuxCNC processes did not exit (pids {linuxcnc_pids()})."
            )
        return self.status()

    def _signal_all(self, pids: List[int], sig: int) -> None:
        for pid in pids:
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                pass  # already gone
            except OSError as exc:
                logger.warning("signal %s to pid %s failed: %s", sig, pid, exc)

    def _wait_for_exit(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not linuxcnc_pids():
                return True
            time.sleep(0.25)
        return not linuxcnc_pids()

    # ------------------------------------------------------------------ #
    # Switch machine                                                      #
    # ------------------------------------------------------------------ #

    def switch(self, profile: Optional[str] = None, start_machine: bool = True) -> dict:
        """Switch the active machine: stop → (compile) → deploy → start.

        Args:
            profile: Optional profile path under ``machine_config/profiles``
                (e.g. ``"starter.cfg"``). When given, the profile is
                compiled with the default compiler before deploying;
                when omitted, the already-staged artifacts in
                ``machine_config/ready_for_deploy`` are deployed.
            start_machine: Start the new machine session after the
                deploy (default ``True``).
        """
        if self.is_running():
            self.stop()

        if profile:
            self._compile_profile(profile)

        staged_service = get_staged_service()
        active_service = get_active_service()
        try:
            deployed = staged_service.deploy_to_active(active_service)
        except FileNotFoundError as exc:
            raise BadRequestError(str(exc)) from exc
        logger.info("Switched active machine: deployed %d artifacts.", len(deployed))

        if not start_machine:
            return self.status()

        # A fresh deploy always means a fresh INI — drop the cached
        # service instances so ``start()`` sees the new file.
        from domain_file_services import reset_service_cache

        reset_service_cache()
        return self.start()

    def _compile_profile(self, profile: str) -> None:
        """Compile ``profile`` with the default compiler into staging."""
        from services.machineconfig import registry as compiler_registry

        ids = compiler_registry.ids()
        if not ids:
            raise ConflictError("No compiler registered — cannot compile profile.")
        compiler = compiler_registry.get(ids[0])

        source = self._resolve_profile_path(profile)
        if not source.exists() or not source.is_file():
            raise NotFoundError(f"Profile not found: {profile}")

        get_staged_service().clear_and_stage(compiler, source)

    def _resolve_profile_path(self, profile: str) -> Path:
        config_service = get_config_service()
        try:
            return config_service.safe_join(profile)
        except ValueError as exc:
            raise BadRequestError(str(exc)) from exc


# Singleton provider
_SERVICE_INSTANCE: Optional[MachineLifecycleService] = None


def get_machine_lifecycle_service() -> MachineLifecycleService:
    global _SERVICE_INSTANCE
    if _SERVICE_INSTANCE is None:
        _SERVICE_INSTANCE = MachineLifecycleService()
    return _SERVICE_INSTANCE
