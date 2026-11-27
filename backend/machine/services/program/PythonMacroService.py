"""Python macros (``macros/<name>.py``): the backend half.

A macro runs in its own process (``macro/py_runner.py``) so Stop and the
E-stop can end it at once, even in an endless loop, and so a crash
cannot take the backend down. Its ``m.…`` calls come back here as JSON
lines and are carried out by the backend:

* ``mdi`` — one MDI line (through ``StateService.run_mdi``, so the UI's
  own commands work too) and the wait until it finished; needs the
  machine ON. Everything else works without homing or even power.
* ``hal_get`` / ``hal_set`` — any pin or signal; setting only what nothing
  else drives (the UI's ``webgui.*`` pins, an unconnected input, a signal
  without a writer).
* ``heater``, ``state``, ``console``.

One macro at a time (shared with ``.macro`` / ``.ngc``). Editing macros
is ``macros.write`` (admins), running them ``macros.run``.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from exceptions import BadRequestError, ConflictError, NotFoundError

logger = logging.getLogger("backend.python_macro")

RUNNER = Path(__file__).resolve().parent / "macro" / "py_runner.py"
#: How long a stopped macro gets before it is killed (s).
TERMINATE_GRACE_S = 1.0
_INTERP_IDLE = 1  # linuxcnc.INTERP_IDLE


class MacroCallError(RuntimeError):
    """A call the macro made failed; the text goes back to the macro."""


class PythonMacroService:
    def __init__(self, handlers: dict[str, Callable[..., Any]] | None = None,
                 python: str | None = None) -> None:
        self._handlers = handlers or default_handlers(self)
        self._python = python or sys.executable
        self._proc: subprocess.Popen[str] | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._abort = threading.Event()
        self.name = ""
        self.last_error = ""

    # -- state ------------------------------------------------------------ #

    def is_running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    @property
    def aborting(self) -> bool:
        return self._abort.is_set()

    def join(self, timeout: float | None = None) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    # -- start / stop -------------------------------------------------- #

    def start(self, name: str, path: Path, args: list[float] | None = None) -> None:
        if not path.is_file():
            raise NotFoundError(f"py not found: {name}")
        with self._lock:
            if self.is_running():
                raise ConflictError("Another macro is still running.")
            self._abort.clear()
            self.name, self.last_error = name, ""
            env = {"PATH": os.environ.get("PATH", ""), "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
            self._proc = subprocess.Popen(
                [self._python, "-I", str(RUNNER), str(path), *(repr(float(a)) for a in args or [])],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                encoding="utf-8", cwd=str(path.parent), env=env, bufsize=1,
            )
            self._thread = threading.Thread(target=self._serve, args=(name, self._proc), name=f"py-macro-{name}",
                                            daemon=True)
            self._thread.start()
        _console(f"Running Python macro '{name}'.")

    def stop(self, reason: str = "stopped") -> bool:
        """End the running macro (and a move it started). ``False``: none ran."""
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return False
        self._abort.set()
        try:
            proc.terminate()
            proc.wait(TERMINATE_GRACE_S)
        except subprocess.TimeoutExpired:
            proc.kill()
        except OSError:
            pass
        handler = self._handlers.get("_abort_motion")
        if handler is not None:
            try:
                handler()
            except Exception as exc:  # noqa: BLE001
                logger.warning("aborting the macro's move failed: %s", exc)
        _console(f"Python macro '{self.name}' {reason}.", level="warning")
        return True

    # -- the conversation with the macro process ----------------------------- #

    def _serve(self, name: str, proc: subprocess.Popen[str]) -> None:
        assert proc.stdout is not None and proc.stdin is not None
        result: dict[str, Any] | None = None
        try:
            for line in proc.stdout:
                try:
                    message = json.loads(line)
                except ValueError:
                    logger.warning("macro %s: not a protocol line: %r", name, line[:200])
                    continue
                if message.get("done"):
                    result = message
                    break
                reply = self._answer(message)
                try:
                    proc.stdin.write(json.dumps(reply) + "\n")
                    proc.stdin.flush()
                except (BrokenPipeError, OSError):
                    break
        finally:
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                proc.kill()
            stderr = (proc.stderr.read() if proc.stderr else "") or ""
            self._finish(name, result, stderr)

    def _answer(self, message: dict[str, Any]) -> dict[str, Any]:
        request_id = message.get("id")
        call = str(message.get("call", ""))
        handler = self._handlers.get(call) if not call.startswith("_") else None
        if handler is None:
            return {"id": request_id, "error": f"unknown call {call!r}"}
        if self._abort.is_set():
            return {"id": request_id, "error": "the macro was stopped"}
        try:
            return {"id": request_id, "result": handler(*(message.get("args") or []))}
        except (MacroCallError, BadRequestError, ConflictError, NotFoundError, ValueError, TypeError) as exc:
            return {"id": request_id, "error": getattr(exc, "detail", None) or str(exc)}
        except Exception as exc:  # noqa: BLE001 - the macro gets the reason, the backend lives on
            logger.exception("macro call %s failed", call)
            return {"id": request_id, "error": f"{call} failed: {exc}"}

    def _finish(self, name: str, result: dict[str, Any] | None, stderr: str) -> None:
        if self._abort.is_set():
            return  # stop() reported it
        error = (result or {}).get("error") if result else (stderr.strip() or "the macro process ended")
        if error:
            self.last_error = str(error).strip()
            last = self.last_error.splitlines()[-1] if self.last_error else "failed"
            _console(f"Python macro '{name}' failed: {last}", level="error")
            logger.warning("Python macro %s failed:\n%s", name, self.last_error)
        else:
            _console(f"Python macro '{name}' finished.")


def _console(text: str, level: str = "info") -> None:
    try:
        from services.machine.ConsoleLogger import LogLevel, get_console_logger

        levels = {"info": LogLevel.INFO, "warning": LogLevel.WARNING, "error": LogLevel.ERROR}
        get_console_logger().log_event(text, level=levels.get(level, LogLevel.INFO), source="MACRO")
    except Exception:  # noqa: BLE001 - logging must not break a macro
        logger.info(text)


# -- what a macro's calls do ------------------------------------------------ #

def _hal_value(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return repr(value)
    raise MacroCallError(f"a HAL value is a bool or a number, not {type(value).__name__}")


def default_handlers(service: PythonMacroService) -> dict[str, Callable[..., Any]]:
    """The real machine: MDI, HAL, heaters, state, the console."""

    def console(text: str, level: str = "info") -> None:
        _console(str(text)[:2000], level if level in ("info", "warning", "error") else "info")

    def mdi(command: str, timeout: float = 600.0) -> None:
        from hardware import get_stat_channel
        from hardware.Connection import MachineState
        from services.machine.StateService import get_state_service

        stat = get_stat_channel()
        if stat is None:
            raise MacroCallError("LinuxCNC is not running")

        def check() -> None:
            stat.poll()
            if service.aborting:
                raise MacroCallError("the macro was stopped")
            if stat.estop:
                raise MacroCallError("the machine is in E-stop")
            if stat.task_state != MachineState.ON.value:
                raise MacroCallError("mdi() needs the machine ON (E-stop released, power on)")

        check()
        get_state_service().run_mdi(str(command))
        deadline = time.monotonic() + float(timeout)
        time.sleep(0.1)  # let the interpreter pick the line up
        while True:
            check()
            if int(getattr(stat, "interp_state", _INTERP_IDLE) or _INTERP_IDLE) == _INTERP_IDLE:
                return
            if time.monotonic() >= deadline:
                raise MacroCallError(f"{command!r} did not finish within {float(timeout):g} s")
            time.sleep(0.05)

    def hal_get(pin: str) -> Any:
        from hardware.Connection import read_hal_pin

        value = read_hal_pin(str(pin))
        if value is None:
            raise MacroCallError(f"cannot read {pin!r} (no such pin or signal)")
        return value

    def hal_set(pin: str, value: Any) -> None:
        from hardware import hal

        name = str(pin)
        if name.startswith("webgui."):
            from dtos.pins.HalPin import HalComponentConnection

            try:
                HalComponentConnection.write(name.removeprefix("webgui."), value)
                return
            except Exception as exc:  # noqa: BLE001
                raise MacroCallError(f"cannot set {name}: {exc}") from None
        text = _hal_value(value)
        errors = []
        for setter in ("set_p", "set_s"):
            fn = getattr(hal, setter, None)
            if fn is None:
                continue
            try:
                fn(name, text)
                return
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc))
        raise MacroCallError(f"cannot set {name}: only an unconnected input pin or a signal without a writer can be "
                             f"set ({'; '.join(errors) or 'no HAL'})")

    def heater(heater_id: str, target: float) -> None:
        from dtos.tools.HeaterDto import HeaterSettingsDTO
        from services.temperature.HeaterService import HeaterService

        HeaterService().set_heater(HeaterSettingsDTO(id=str(heater_id), target_temperature=float(target),
                                                     enable=float(target) > 0))

    def state() -> dict[str, Any]:
        from hardware import get_stat_channel
        from hardware.Connection import MachineState
        from services.machine.BaseThreadService import get_base_thread_service

        stat = get_stat_channel()
        out: dict[str, Any] = {"linuxcnc": stat is not None}
        if stat is not None:
            stat.poll()
            out.update(
                estop=bool(stat.estop),
                on=stat.task_state == MachineState.ON.value,
                homed=[bool(h) for h in list(getattr(stat, "homed", []))[:9]],
                position=[round(float(v), 4) for v in list(getattr(stat, "actual_position", []))[:9]],
                program=str(getattr(stat, "file", "") or ""),
                interp_state=int(getattr(stat, "interp_state", 0) or 0),
            )
        try:
            snapshot = get_base_thread_service().get_snapshot().model_dump(exclude_none=True)
            out["temperatures"] = {
                sid: {"actual": s.get("actual"), "target": s.get("target")}
                for sid, s in (snapshot.get("sensors") or {}).items() if isinstance(s, dict)
            }
        except Exception as exc:  # noqa: BLE001
            logger.debug("macro state: temperatures unavailable: %s", exc)
            out["temperatures"] = {}
        return out

    def abort_motion() -> None:
        from hardware import execute_sync_cmd

        execute_sync_cmd("abort")

    return {"console": console, "mdi": mdi, "hal_get": hal_get, "hal_set": hal_set, "heater": heater,
            "state": state, "_abort_motion": abort_motion}


_SERVICE: PythonMacroService | None = None


def get_python_macro_service() -> PythonMacroService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = PythonMacroService()
    return _SERVICE


__all__ = ["MacroCallError", "PythonMacroService", "get_python_macro_service"]
