"""Runs one Python macro (``macros/<name>.py``) in its own process.

Started by ``services.program.PythonMacroService`` as
``python -I py_runner.py <file>``; only the standard library, nothing of
the backend. The macro defines ``run(m)``; every ``m.…`` call is a JSON
line on stdout (``{"id": n, "call": ..., "args": [...]}``) answered on
stdin (``{"id": n, "result": ...}`` or ``{"id": n, "error": "..."}``) —
the backend does the work (MDI, HAL, heaters). ``print()`` goes to the
console. The last line is ``{"done": true}`` or ``{"done": true,
"error": "<traceback>"}``.

The process can be killed at any time (Stop, E-stop): that is why a
macro runs here and not in a thread of the backend.
"""
from __future__ import annotations

import io
import json
import sys
import time
import traceback
from typing import Any, Callable


class MacroError(RuntimeError):
    """The backend refused or failed a call (the message says why)."""


class _Link:
    def __init__(self, out: Any, inp: Any) -> None:
        self._out, self._in, self._ids = out, inp, 0

    def call(self, name: str, *args: Any) -> Any:
        self._ids += 1
        self._out.write(json.dumps({"id": self._ids, "call": name, "args": list(args)}) + "\n")
        self._out.flush()
        line = self._in.readline()
        if not line:
            raise SystemExit("backend gone")
        reply = json.loads(line)
        if "error" in reply:
            raise MacroError(reply["error"])
        return reply.get("result")

    def send(self, message: dict[str, Any]) -> None:
        self._out.write(json.dumps(message) + "\n")
        self._out.flush()


class Hal:
    def __init__(self, link: _Link) -> None:
        self._link = link

    def get(self, pin: str) -> Any:
        """A HAL pin or signal's value (``webgui.<id>``, ``motion.in-position``, ...)."""
        return self._link.call("hal_get", pin)

    def set(self, pin: str, value: Any) -> None:
        """Set a pin nothing else drives: the UI's ``webgui.*`` pins, an
        unconnected input, or a signal without a writer."""
        self._link.call("hal_set", pin, value)


class Machine:
    """What a macro can do: ``run(m)`` gets one of these."""

    def __init__(self, link: _Link, args: list[Any]) -> None:
        self._link = link
        self.hal = Hal(link)
        #: Numbers the macro was started with (a macro button, the console).
        self.args = args

    # -- talking ---------------------------------------------------------- #
    def console(self, text: Any, level: str = "info") -> None:
        """A line in the UI's console (``level``: info, warning, error)."""
        self._link.call("console", str(text), level)

    # -- the machine ------------------------------------------------------- #
    def mdi(self, command: str, timeout: float = 600.0) -> None:
        """Run one MDI line (G-code, or the UI's own: G28, SET_LED, ACE_*, ...)
        and wait until it finished. Needs the machine ON."""
        self._link.call("mdi", command, timeout)

    def state(self) -> dict[str, Any]:
        """E-stop, on, homed axes, position, program state, temperatures."""
        return self._link.call("state")

    def temp(self, sensor: str) -> float | None:
        """A heater / sensor's temperature (°C), by id (``extruder``, ``heater_bed``, ...)."""
        reading = (self.state().get("temperatures") or {}).get(sensor) or {}
        return reading.get("actual")

    def heater(self, heater: str, target: float) -> None:
        """A heater's target (°C); 0 turns it off."""
        self._link.call("heater", heater, float(target))

    # -- waiting ------------------------------------------------------------ #
    @staticmethod
    def sleep(seconds: float) -> None:
        time.sleep(seconds)

    def wait_until(self, condition: Callable[[], bool], timeout: float = 60.0, poll: float = 0.2) -> None:
        """Wait until ``condition()`` is true; :class:`MacroError` after ``timeout`` s."""
        deadline = time.monotonic() + timeout
        while not condition():
            if time.monotonic() >= deadline:
                raise MacroError(f"timed out after {timeout:g} s")
            time.sleep(poll)

    def wait_pin(self, pin: str, value: Any = True, timeout: float = 60.0, poll: float = 0.05) -> None:
        """Wait until HAL ``pin`` equals ``value``."""
        self.wait_until(lambda: self.hal.get(pin) == value, timeout, poll)


class _Console(io.TextIOBase):
    """``print()`` in a macro -> console lines."""

    def __init__(self, link: _Link) -> None:
        self._link, self._buf = link, ""

    def write(self, text: str) -> int:
        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.strip():
                self._link.call("console", line, "info")
        return len(text)

    def flush(self) -> None:
        if self._buf.strip():
            self._link.call("console", self._buf, "info")
        self._buf = ""


def main(argv: list[str]) -> int:
    path, args = argv[1], [float(a) for a in argv[2:]]
    link = _Link(sys.stdout, sys.stdin)
    console = _Console(link)
    sys.stdout = console  # print() -> the console; the protocol keeps the real stdout
    try:
        source = open(path, encoding="utf-8").read()
        scope: dict[str, Any] = {"__name__": "__macro__", "__file__": path, "MacroError": MacroError}
        exec(compile(source, path, "exec"), scope)  # noqa: S102 - the macro is the operator's own code
        run = scope.get("run")
        if not callable(run):
            raise MacroError("the macro has no run(m) function")
        run(Machine(link, args))
        console.flush()
        link.send({"done": True})
        return 0
    except BaseException:  # noqa: BLE001 - every failure is reported
        try:
            console.flush()
        except BaseException:  # noqa: BLE001
            pass
        link.send({"done": True, "error": traceback.format_exc(limit=8)})
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
