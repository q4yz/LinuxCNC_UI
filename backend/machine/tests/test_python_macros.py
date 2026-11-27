"""Python macros (macros/<name>.py): the runner process, the calls it makes
back to the backend, stopping it, and the start route's kind routing."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from services.program.PythonMacroService import MacroCallError, PythonMacroService


class Recorder:
    """Fake machine: records the calls, answers like the real handlers."""

    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.pins: dict[str, object] = {"webgui.door": False}
        self.console: list[tuple[str, str]] = []

    def handlers(self) -> dict[str, object]:
        def console(text, level="info"):
            self.console.append((level, text))

        def mdi(command, timeout=600.0):
            if command.startswith("G0 X999"):
                raise MacroCallError("soft limit")
            self.calls.append(("mdi", command))

        def hal_get(pin):
            if pin not in self.pins:
                raise MacroCallError(f"cannot read {pin!r}")
            return self.pins[pin]

        def hal_set(pin, value):
            self.pins[pin] = value
            self.calls.append(("hal_set", pin, value))

        def heater(heater_id, target):
            self.calls.append(("heater", heater_id, target))

        def state():
            return {"estop": False, "on": True, "temperatures": {"extruder": {"actual": 205.0, "target": 210.0}}}

        return {"console": console, "mdi": mdi, "hal_get": hal_get, "hal_set": hal_set, "heater": heater,
                "state": state, "_abort_motion": lambda: self.calls.append(("abort",))}


def macro(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / f"{name}.py"
    path.write_text(body, encoding="utf-8")
    return path


def run_to_end(service: PythonMacroService, timeout: float = 20.0) -> None:
    service.join(timeout)
    assert not service.is_running(), "macro still running"


def test_a_macro_drives_the_machine_through_the_api(tmp_path):
    rec = Recorder()
    service = PythonMacroService(handlers=rec.handlers())
    path = macro(tmp_path, "warmup", """
def run(m):
    print("warming up", m.args)
    m.heater("extruder", 210)
    m.hal.set("webgui.light", True)
    assert m.hal.get("webgui.door") is False
    assert m.temp("extruder") == 205.0
    m.wait_until(lambda: m.temp("extruder") > 200, timeout=2)
    for x in (10, 20):
        m.mdi(f"G0 X{x}")
    m.console("done", "warning")
""")
    service.start("warmup", path, [1.5, 2])
    run_to_end(service)
    assert service.last_error == ""
    assert rec.calls == [("heater", "extruder", 210.0), ("hal_set", "webgui.light", True),
                         ("mdi", "G0 X10"), ("mdi", "G0 X20")]
    assert ("info", "warming up [1.5, 2.0]") in rec.console and ("warning", "done") in rec.console


def test_a_refused_call_is_an_exception_the_macro_can_catch(tmp_path):
    rec = Recorder()
    service = PythonMacroService(handlers=rec.handlers())
    path = macro(tmp_path, "careful", """
def run(m):
    try:
        m.mdi("G0 X999")
    except MacroError as exc:
        print("refused:", exc)
    try:
        m.hal.get("nope.pin")
    except MacroError as exc:
        print("refused:", exc)
    m.wait_pin("webgui.door", False, timeout=1)
""")
    service.start("careful", path)
    run_to_end(service)
    assert service.last_error == ""
    texts = [t for _, t in rec.console]
    assert "refused: soft limit" in texts and "refused: cannot read 'nope.pin'" in texts


def test_a_crash_is_reported_with_its_reason(tmp_path):
    rec = Recorder()
    service = PythonMacroService(handlers=rec.handlers())
    service.start("bad", macro(tmp_path, "bad", "def run(m):\n    1 / 0\n"))
    run_to_end(service)
    assert "ZeroDivisionError" in service.last_error
    service.start("norun", macro(tmp_path, "norun", "x = 1\n"))
    run_to_end(service)
    assert "no run(m) function" in service.last_error
    service.start("syntax", macro(tmp_path, "syntax", "def run(m)\n    pass\n"))
    run_to_end(service)
    assert "SyntaxError" in service.last_error


def test_stop_ends_even_an_endless_loop_and_aborts_motion(tmp_path):
    rec = Recorder()
    service = PythonMacroService(handlers=rec.handlers())
    service.start("forever", macro(tmp_path, "forever", "def run(m):\n    while True:\n        pass\n"))
    time.sleep(0.3)
    assert service.is_running()
    began = time.monotonic()
    assert service.stop("stopped by the operator") is True
    run_to_end(service, 5)
    assert time.monotonic() - began < 3
    assert ("abort",) in rec.calls
    assert service.stop() is False  # nothing runs any more


def test_one_macro_at_a_time(tmp_path):
    from exceptions import ConflictError, NotFoundError

    service = PythonMacroService(handlers=Recorder().handlers())
    service.start("slow", macro(tmp_path, "slow", "def run(m):\n    m.sleep(2)\n"))
    with pytest.raises(ConflictError):
        service.start("slow", tmp_path / "slow.py")
    service.stop()
    run_to_end(service)
    with pytest.raises(NotFoundError):
        service.start("missing", tmp_path / "missing.py")


def test_the_macro_process_is_isolated(tmp_path):
    """-I: no PYTHONPATH, no backend packages; cwd is the macros folder."""
    rec = Recorder()
    service = PythonMacroService(handlers=rec.handlers())
    service.start("probe", macro(tmp_path, "probe", """
import os, sys
def run(m):
    try:
        import services  # the backend's package must not be importable
        print("leak")
    except ImportError:
        print("isolated")
    print("cwd", os.path.basename(os.getcwd()))
"""))
    run_to_end(service)
    texts = [t for _, t in rec.console]
    assert "isolated" in texts and f"cwd {tmp_path.name}" in texts


def test_the_start_route_runs_py_without_a_machine_preflight(tmp_path, monkeypatch):
    from services.program import MacroExecutionService as module

    started: list[tuple] = []

    class FakePython:
        def is_running(self):
            return False

        def start(self, name, path, args):
            started.append((name, path.name, args))

        def stop(self, reason):
            return True

    class FakeFiles:
        def safe_join(self, name):
            return tmp_path / name

    monkeypatch.setattr(module, "get_macro_service", lambda: FakeFiles())
    service = module.MacroExecutionService()
    monkeypatch.setattr(service, "_python", lambda: FakePython())
    service.start_macro("warmup", "py", [3.0])
    service.start_macro("warmup.py", "py", [])
    assert started == [("warmup", "warmup.py", [3.0]), ("warmup", "warmup.py", [])]
    assert service.stop_macro() is True


def test_the_real_handlers_import_and_answer():
    """The real machine calls (fakes above): every import resolves, and an
    unreadable pin is a MacroCallError the macro sees — not a crash."""
    from services.program.PythonMacroService import default_handlers

    handlers = default_handlers(PythonMacroService(handlers={}))
    state = handlers["state"]()
    assert "linuxcnc" in state and "temperatures" in state
    # the mock HAL answers 0.0 for any name (real HAL refuses unknown pins,
    # which hal_get turns into a MacroCallError)
    assert handlers["hal_get"]("no.such.pin") is not None
    with pytest.raises(MacroCallError):
        handlers["hal_set"]("motion.x", "text")  # not a bool / number
    handlers["console"]("hello from a test")


def test_pressing_the_e_stop_stops_a_macro_but_a_macro_started_in_e_stop_runs(monkeypatch):
    """The telemetry loop stops a Python macro on the E-stop's rising edge only."""
    import asyncio
    import services.program.PythonMacroService as module
    from services.machine.ServoThreadService import ServoThreadService

    stops: list[str] = []

    class FakeMacro:
        aborting = False

        def is_running(self):
            return True

        def stop(self, reason):
            stops.append(reason)

    class Stat:
        task_state = 1
        estop = 1

    stat = Stat()
    monkeypatch.setattr(module, "get_python_macro_service", lambda: FakeMacro())
    svc = ServoThreadService()
    svc.active_connections = []
    monkeypatch.setattr(svc.state_service, "get_polled_stat", lambda: stat)
    monkeypatch.setattr(svc.state_service, "get_error_history", lambda: [])
    monkeypatch.setattr(svc.heater_safety, "observe", lambda state: None)

    async def ticks(n):
        task = asyncio.create_task(svc.telemetry_loop())
        await asyncio.sleep(0.1 * n + 0.05)
        task.cancel()

    svc._was_estop = True  # the machine sat in E-stop when the macro started
    asyncio.run(ticks(2))
    assert stops == []
    stat.estop = 0
    asyncio.run(ticks(2))
    stat.estop = 1  # pressed while it runs
    asyncio.run(ticks(2))
    assert stops == ["stopped by the E-stop"]
