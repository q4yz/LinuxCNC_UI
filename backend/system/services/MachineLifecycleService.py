"""Machine process lifecycle — the system service's process supervisor.

The system service is the always-running half of the backend split,
so it owns the LinuxCNC *process* lifecycle: detecting whether a
``linuxcnc`` session is alive, starting the default machine's INI,
stopping the session again, and remembering which machine is the
"default" (the one generic "Start machine" buttons launch).

The default machine is persisted in
``machine_config/default_machine.json`` and points at a machine
folder under ``machine_config/machines/`` whose INI lives at
``<machine>/config/machine.ini`` — the ``machine_config/active/``
deploy flow is deprecated and no longer part of the start path.

Starting literally runs the console command::

    linuxcnc -r <machine_config/machines/<default>/config/machine.ini>

The ``-r`` flag (see ``linuxcnc(1)``) disables LinuxCNC's own default
behaviour of redirecting its stdout/stderr to
``~/linuxcnc_print.txt`` / ``~/linuxcnc_debug.txt`` whenever stdin
isn't a tty — true for every detached session we spawn — so its
output (including a crash's error text) actually reaches the fds we
gave it instead of vanishing into those two files. The process is
spawned detached (``start_new_session=True``) with its stdout+stderr
tee'd into ``logs/linuxcnc_console.log`` at the repository root and
``DISPLAY`` inherited (defaulting to ``:0`` so the LinuxCNC GUI opens
on the machine's console display). The launch command can be
overridden with the ``LINUXCNC_START_COMMAND`` env var using a
``{ini}`` placeholder, e.g. ``"xterm -e linuxcnc -r {ini}"`` — an
override that drops ``-r`` falls back on
:meth:`MachineLifecycleService.console_log` also reading those two
home-directory files directly. ``_build_command`` additionally
prefixes ``stdbuf -oL -eL`` when available — see its docstring for
why a hard LinuxCNC abort can still lose buffered output even with
``-r`` in place.

:meth:`MachineLifecycleService.console_log` surfaces the tail of
every known LinuxCNC log to the UI (``GET
/api/v1/system/machine/log``) so an operator can see why a session
failed without shell access. An immediate crash (``start()``
returning within the 0.5s poll window) folds the merged tail straight
into the raised error, since that is the most common "it just won't
start" case.
"""
from __future__ import annotations

import json
import logging
import os
import shlex
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from exceptions import BadRequestError, ConflictError, NotFoundError

from domain_file_services import get_active_service, get_machine_service
from domain_file_services.paths import ACTIVE_DIR

logger = logging.getLogger("backend.system.machine_lifecycle")

#: LinuxCNC session process names — mirrors the guard in
#: ``scripts/update.sh`` (linuxcnc/emc) plus the background daemons a
#: session spawns (milltask, linuxcncsvr).
PROCESS_PATTERNS: tuple[str, ...] = ("linuxcnc", "emc", "milltask", "linuxcncsvr")

#: Console log for started LinuxCNC sessions (repository root).
_REPO_ROOT = Path(__file__).resolve().parents[3]
_CONSOLE_LOG = _REPO_ROOT / "logs" / "linuxcnc_console.log"

#: LinuxCNC's own launcher redirects its stdout/stderr to these two
#: files under the user's home directory the moment it decides it's
#: not talking to an interactive terminal — which is exactly our
#: case, since we spawn it detached. When that redirect fires it
#: happens *inside* the child, downstream of our own
#: ``stdout=log_handle`` on ``Popen`` — our tee never sees a single
#: byte, no matter the buffering, because the child re-pointed its
#: own fds elsewhere before printing anything. These paths are
#: LinuxCNC's documented behaviour, not configurable by us; read them
#: alongside our own tee so a crash is visible regardless of which
#: path it actually took.
_HOME_PRINT_LOG = Path.home() / "linuxcnc_print.txt"
_HOME_DEBUG_LOG = Path.home() / "linuxcnc_debug.txt"

#: Bytes read from the tail of each log source per request — caps
#: memory when a log has accumulated many sessions' worth of output.
_LOG_TAIL_MAX_BYTES = 512 * 1024

#: Lines of console-log tail folded into the crash error message so
#: an immediate failure (bad INI, realtime error, ...) is visible in
#: the UI without a separate log request.
_CRASH_LOG_LINES = 30

#: Persisted default-machine selection, stored as
#: ``machine_config/default_machine.json`` (sibling of ``machines/``).
_DEFAULT_MACHINE_FILE_NAME = "default_machine.json"

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

    # ------------------------------------------------------------------ #
    # Default machine (persisted selection)                               #
    # ------------------------------------------------------------------ #

    def _default_machine_file(self) -> Path:
        """``machine_config/default_machine.json`` (call-time path lookup
        so tests can repoint ``MACHINE_CONFIG_DIR``)."""
        from domain_file_services.paths import MACHINE_CONFIG_DIR

        return Path(MACHINE_CONFIG_DIR) / _DEFAULT_MACHINE_FILE_NAME

    def default_machine(self) -> Optional[str]:
        """Name of the persisted default machine, if any."""
        try:
            data = json.loads(self._default_machine_file().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        name = data.get("default_machine") if isinstance(data, dict) else None
        return name if isinstance(name, str) and name else None

    def machine_ini(self, machine: str) -> Path:
        """Absolute INI path of a machine folder.

        Two layouts are accepted (first match wins):

          * ``machines/<machine>/config/machine.ini``   (manual layout)
          * ``machines/<machine>/configs/machine.ini``  (generator output)

        Raises:
            BadRequestError: ``machine`` escapes ``machines/``.
            NotFoundError: the INI exists in neither layout.
        """
        try:
            base = get_machine_service().safe_join(machine)
        except ValueError as exc:
            raise BadRequestError(str(exc)) from exc

        for relative in ("config/machine.ini", "configs/machine.ini"):
            candidate = base / relative
            if candidate.is_file():
                return candidate

        raise NotFoundError(
            f"No INI for machine '{machine}' — looked at "
            f"machines/{machine}/config/machine.ini and "
            f"machines/{machine}/configs/machine.ini."
        )

    def default_ini(self) -> Optional[Path]:
        """INI of the persisted default machine, or ``None`` when unset
        (or the selected machine has since been deleted)."""
        name = self.default_machine()
        if not name:
            return None
        try:
            return self.machine_ini(name)
        except (NotFoundError, BadRequestError):
            return None

    def set_default_machine(self, machine: str) -> Path:
        """Persist ``machine`` as the default ("Select as main").

        Returns the machine's INI path. Raises when the machine folder
        carries no INI (``config/`` or ``configs/`` layout) — a default
        that cannot start would only move the failure to a later, more
        confusing place.
        """
        ini = self.machine_ini(machine)
        path = self._default_machine_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"default_machine": machine}, indent=2) + "\n",
            encoding="utf-8",
        )
        logger.info("Default machine set to '%s' (%s).", machine, ini)
        return ini

    def _read_log_tail(self, path: Path) -> Optional[str]:
        """Last ``_LOG_TAIL_MAX_BYTES`` bytes of ``path`` (seeking from
        the end so a log grown across many sessions is never loaded
        into memory in full), or ``None`` when it doesn't exist."""
        if not path.is_file():
            return None
        try:
            with open(path, "rb") as fh:
                fh.seek(0, os.SEEK_END)
                size = fh.tell()
                fh.seek(max(0, size - _LOG_TAIL_MAX_BYTES))
                raw = fh.read()
            return raw.decode("utf-8", errors="replace")
        except OSError as exc:
            logger.warning("Could not read log %s: %s", path, exc)
            return None

    def console_log(self, lines: int = 200) -> Dict[str, Any]:
        """Tail of every known LinuxCNC log, merged.

        Three sources are checked, because we don't control which one
        actually gets LinuxCNC's error text: our own tee
        (``logs/linuxcnc_console.log``) only receives it when
        LinuxCNC treats its stdout as a plain pipe; the moment it
        decides it isn't talking to an interactive terminal (true for
        every detached session we spawn), its own launcher redirects
        to ``~/linuxcnc_print.txt`` / ``~/linuxcnc_debug.txt``
        instead, upstream of anything we can intercept. Each source
        that exists gets its own tail (last ``lines`` lines, capped at
        ``_LOG_TAIL_MAX_BYTES``) under a header naming it, so a crash
        is visible no matter which path it took.
        """
        sources = [
            ("logs/linuxcnc_console.log (this UI's own tee)", _CONSOLE_LOG),
            ("~/linuxcnc_print.txt (LinuxCNC's stdout)", _HOME_PRINT_LOG),
            ("~/linuxcnc_debug.txt (LinuxCNC's debug/error log)", _HOME_DEBUG_LOG),
        ]

        sections: List[str] = []
        any_exists = False
        for label, path in sources:
            text = self._read_log_tail(path)
            if text is None:
                continue
            any_exists = True
            tail_lines = text.splitlines()[-max(1, lines):] if text else []
            sections.append(f"--- {label} ---\n" + ("\n".join(tail_lines) or "(empty)"))

        return {
            "path": str(_CONSOLE_LOG),
            "exists": any_exists,
            "log": "\n\n".join(sections),
        }

    def status(self) -> Dict[str, Any]:
        ini = self.default_ini()
        name = self.default_machine()
        return {
            "running": self.is_running(),
            "pids": linuxcnc_pids(),
            # ``machine_name`` is kept as a deprecated alias of
            # ``default_machine`` so the existing generated API model
            # stays valid until the client is regenerated.
            "machine_name": name,
            "default_machine": name,
            "ini_path": str(ini) if ini else None,
            "ini_exists": ini is not None,
        }

    # ------------------------------------------------------------------ #
    # Start                                                               #
    # ------------------------------------------------------------------ #

    def start(self, machine: Optional[str] = None) -> Dict[str, Any]:
        """Run ``linuxcnc <ini>`` as a console process.

        Args:
            machine: Optional machine folder name under
                ``machine_config/machines``. When given, it is
                persisted as the default ("start implies main") and
                its ``config/machine.ini`` is launched. When omitted,
                the persisted default machine is started; a
                ``NotFoundError`` is raised when no default has been
                selected yet.
        """
        if self.is_running():
            raise ConflictError(
                f"LinuxCNC is already running (pids {linuxcnc_pids()})."
            )

        if machine is not None:
            # Starting a specific machine makes it the default — one
            # source of truth for "which machine is main".
            self.set_default_machine(machine)
        elif self.default_machine() is None:
            raise NotFoundError(
                "No default machine selected — select one with "
                "'Select as main' in the Machines explorer."
            )

        ini = self.machine_ini(self.default_machine())

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
                # Relative INI references (e.g. HAL includes) resolve
                # against the machine's own config folder — the
                # deprecated active/ dir is no longer part of the
                # start path.
                stdin=subprocess.PIPE,
                cwd=str(ini.parent),
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
            tail = self.console_log(lines=_CRASH_LOG_LINES)["log"]
            detail = f"LinuxCNC exited immediately (code {process.returncode})."
            if tail:
                detail += f"\n\n--- last {_CRASH_LOG_LINES} lines of {_CONSOLE_LOG.name} ---\n{tail}"
            else:
                detail += f" See {_CONSOLE_LOG} for the console output."
            raise BadRequestError(detail)

        status = self.status()
        status["started_pid"] = process.pid
        return status

    def _build_command(self, ini: Path) -> List[str]:
        """Resolve the launch command (``LINUXCNC_START_COMMAND`` override).

        The default command is ``linuxcnc -r <ini>``. Per ``linuxcnc(1)``,
        ``-r`` "disable[s] redirection of stdout and stderr to
        ``~/linuxcnc_print.txt`` and ``~/linuxcnc_debug.txt`` when
        stdin is not a tty" — which is exactly our case, since every
        session we spawn is detached. Without ``-r`` that redirect
        happens *inside* the child, downstream of our own
        ``stdout=log_handle`` on ``Popen``, so a crash's error text
        lands in those two home-directory files instead of
        ``_CONSOLE_LOG`` and our tee stays empty — LinuxCNC's on-screen
        error dialog still shows it (X11, not stdio), which is how
        the gap surfaces: visible on the machine's monitor, invisible
        to the UI. ``-r`` keeps everything flowing through the fds we
        actually captured. (``console_log()`` still also reads those
        two files as a fallback, for an ``LINUXCNC_START_COMMAND``
        override that omits ``-r``.)

        Also prefixed with ``stdbuf -oL -eL`` when available: with
        the redirect gone, LinuxCNC's plain-C-stdio output is now
        flowing into our file, but stdio still switches from
        line-buffered to fully block buffered once it's not a tty —
        so a hard abort (realtime error, segfault) can still lose
        whatever sat in that buffer unflushed. ``stdbuf`` forces line
        buffering regardless of the destination.
        """
        template = os.environ.get("LINUXCNC_START_COMMAND", "").strip()
        command = shlex.split(template.format(ini=str(ini))) if template else ["linuxcnc", "-r", str(ini)]
        if shutil.which("stdbuf"):
            command = ["stdbuf", "-oL", "-eL"] + command
        return command

    # ------------------------------------------------------------------ #
    # Stop                                                                #
    # ------------------------------------------------------------------ #

    def stop(self, grace_seconds: float = _STOP_GRACE_SECONDS) -> Dict[str, Any]:
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

    def switch(self, machine: Optional[str] = None, start_machine: bool = True) -> Dict[str, Any]:
        """Switch the active machine: stop → (deploy) → start.

        Args:
            machine: Optional path under ``machine_config/machines``
                to a generated machine (e.g. ``"PrintNC"`` or
                ``"PrintNC/configs"`` — see
                :func:`resolve_machine_configs_dir`). Generate it
                first with ``POST /modules/machineconfig/machines/generate``.
                When given, that machine's templates are deployed
                into ``machine_config/active`` before starting; when
                omitted, the machine currently in ``active/`` is
                simply restarted.
            start_machine: Start the new machine session after the
                deploy (default ``True``).
        """
        if self.is_running():
            self.stop()

        if machine:
            self._deploy_machine(machine)

        if not start_machine:
            return self.status()

        # A fresh deploy always means a fresh INI — drop the cached
        # service instances so ``start()`` sees the new file.
        from domain_file_services import reset_service_cache

        reset_service_cache()
        return self.start()

    def _deploy_machine(self, machine: str) -> None:
        """Deploy a generated machine's templates into ``active/``."""
        from services.machinetemplates import resolve_machine_configs_dir

        machine_service = get_machine_service()
        try:
            configs_dir = resolve_machine_configs_dir(machine_service, machine)
        except ValueError as exc:
            raise BadRequestError(str(exc)) from exc
        if not configs_dir.exists() or not configs_dir.is_dir():
            raise NotFoundError(f"Machine not found: {machine}")

        deployed = get_active_service().deploy_from(configs_dir)
        logger.info(
            "Switched active machine to '%s': deployed %d artifacts.",
            machine,
            len(deployed),
        )


# Singleton provider
_SERVICE_INSTANCE: Optional[MachineLifecycleService] = None


def get_machine_lifecycle_service() -> MachineLifecycleService:
    global _SERVICE_INSTANCE
    if _SERVICE_INSTANCE is None:
        _SERVICE_INSTANCE = MachineLifecycleService()
    return _SERVICE_INSTANCE
