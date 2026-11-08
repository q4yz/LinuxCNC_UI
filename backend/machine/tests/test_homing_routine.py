"""The ``[homing_override]`` routine runner (`HomingRoutineService`):
MDI lines and ``G28`` home steps in order, stopping at the first failure,
and the "home first" program guard."""
from __future__ import annotations

import pytest

import services.HomingRoutineService as module
import services.MacroExecutionService as macro_module
from exceptions import BadRequestError, ConflictError
from hardware.Connection import MachineState

ROUTINE = "G91\nG0 Z5\nG90\nG28 X\nG28 Y\nG53 G0 X100 Y100\nG28 Z"
AXES = [
    {"id": "x", "joint_numbers": [0]},
    {"id": "y", "joint_numbers": [1, 2]},  # a gantry: two joints, homed together
    {"id": "z", "joint_numbers": [3]},
]


class FakeConfig:
    def __init__(self, override):
        self.payload = {"homing_override": override, "axes": AXES}

    def load_payload(self):
        return self.payload

    def get_axes(self):
        return AXES


class FakeStat:
    def __init__(self, joints=4):
        self.estop = False
        self.task_state = MachineState.ON.value
        self.task_mode = 3  # MDI
        self.interp_state = 1  # idle
        self.homed = [0] * joints
        self.joint = [{"homing": 0} for _ in range(joints)]

    def poll(self):
        pass


@pytest.fixture
def machine(monkeypatch):
    stat = FakeStat()
    calls: list[tuple] = []
    unhomeable: set[int] = set()

    def execute_sync_cmd(name, timeout=0, *args):
        calls.append((name, *args))
        if name == "unhome":
            stat.homed[args[0]] = 0
        if name == "home":
            joint = args[0]
            joints = range(len(stat.homed)) if joint == -1 else [1, 2] if joint == 1 else [joint]
            for j in joints:
                if j not in unhomeable:
                    stat.homed[j] = 1
        return {"status": "success"}

    def dispatch_mdi(line, ack_timeout=1.0):
        calls.append(("mdi", line))
        return None

    monkeypatch.setattr(module, "execute_sync_cmd", execute_sync_cmd)
    monkeypatch.setattr(module, "dispatch_mdi", dispatch_mdi)
    monkeypatch.setattr(module, "get_stat_channel", lambda: stat)
    monkeypatch.setattr(module, "HOME_START_GRACE_S", 0.05)
    monkeypatch.setattr(module, "_POLL_S", 0)
    monkeypatch.setattr(macro_module, "_IDLE_POLL_S", 0)
    events: list[tuple[str, str]] = []

    class Console:
        def log_event(self, message, level=None, source=None):
            events.append((str(level), message))

    monkeypatch.setattr(module, "get_console_logger", lambda: Console())

    class Macros:
        running = False

        def is_running(self):
            return self.running

    macros = Macros()

    def service(override={"gcode": ROUTINE, "axes": "xyz"}):
        return module.HomingRoutineService(config=FakeConfig(override), macros=macros)

    return type("M", (), {"stat": stat, "calls": calls, "events": events, "unhomeable": unhomeable,
                          "service": staticmethod(service), "macros": macros})


def _run(service):
    service.start()
    service.join(timeout=5)


def test_routine_runs_in_order(machine):
    _run(machine.service())
    flat = [c for c in machine.calls if c[0] in ("mdi", "home")]
    assert flat == [
        ("mdi", "G91"), ("mdi", "G0 Z5"), ("mdi", "G90"),
        ("home", 0), ("home", 1), ("mdi", "G53 G0 X100 Y100"), ("home", 3),
    ]
    # Every home is sent in MANUAL mode, joint mode.
    i = machine.calls.index(("home", 0))
    assert machine.calls[i - 2:i] == [("mode", module._MODE_MANUAL), ("teleop_enable", 0)]
    assert machine.stat.homed == [1, 1, 1, 1]
    assert machine.events[-1][1] == "Homing routine finished."


def test_bare_g28_homes_every_joint(machine):
    _run(machine.service({"gcode": "G0 Z5\nG28", "axes": "xyz"}))
    assert ("home", -1) in machine.calls
    assert machine.stat.homed == [1, 1, 1, 1]


def test_stops_at_a_joint_that_does_not_home(machine):
    machine.unhomeable.add(1)  # Y's switch is never reached
    _run(machine.service())
    assert ("home", 3) not in machine.calls
    assert ("mdi", "G53 G0 X100 Y100") not in machine.calls
    level, message = machine.events[-1]
    assert "aborted" in message and "'G28 Y'" in message and "joint(s) 1, 2" in message


def test_estop_stops_the_routine(machine):
    real = module.dispatch_mdi

    def estop_on_g90(line, ack_timeout=1.0):
        if line == "G90":
            machine.stat.estop = True
        return real(line, ack_timeout)

    module.dispatch_mdi = estop_on_g90
    try:
        _run(machine.service())
    finally:
        module.dispatch_mdi = real
    assert not any(c[0] == "home" for c in machine.calls)
    assert "E-Stop" in machine.events[-1][1]


def test_start_checks_the_machine(machine):
    with pytest.raises(BadRequestError):
        machine.service(None).start()
    machine.stat.task_state = MachineState.OFF.value
    with pytest.raises(BadRequestError):
        machine.service().start()
    machine.stat.task_state = MachineState.ON.value
    machine.macros.running = True
    with pytest.raises(ConflictError):
        machine.service().start()


def test_applies_to(machine):
    service = machine.service({"gcode": ROUTINE, "axes": "z"})
    assert service.applies_to("all") and service.applies_to("z")
    assert not service.applies_to("x")
    assert not machine.service(None).applies_to("all")


def test_program_guard(machine):
    service = machine.service()
    with pytest.raises(ConflictError, match="joint\\(s\\) 0, 1, 2, 3"):
        service.require_homed()
    machine.stat.homed = [1, 1, 1, 1]
    service.require_homed()
    # Without a routine LinuxCNC enforces homing itself: no guard.
    machine.stat.homed = [0, 0, 0, 0]
    machine.service(None).require_homed()


def test_home_button_runs_the_routine(machine, monkeypatch):
    from services.AxisService import AxisService

    service = machine.service({"gcode": ROUTINE, "axes": "z"})
    monkeypatch.setattr(module, "get_homing_routine_service", lambda: service)
    started = []
    monkeypatch.setattr(service, "start", lambda: started.append(True))
    AxisService().home_single_axes("all")
    AxisService().home_single_axes("z")
    assert started == [True, True]


def test_switchless_axis_is_homed_in_place_at_the_end(machine):
    axes = AXES + [{"id": "a", "joint_numbers": [4]}]
    machine.stat.homed = [0] * 5
    machine.stat.joint = [{"homing": 0} for _ in range(5)]
    service = machine.service({"gcode": ROUTINE, "axes": "xyz", "home_in_place": ["a"]})
    service._config.payload["axes"] = axes
    service._config.get_axes = lambda: axes
    _run(service)
    homes = [c for c in machine.calls if c[0] == "home"]
    assert homes == [("home", 0), ("home", 1), ("home", 3), ("home", 4)]
    assert machine.stat.homed == [1] * 5
    assert machine.events[-1][1] == "Homing routine finished."


# -- Z homed on the probe (probe:z_virtual_endstop) ---------------------------- #

VIRTUAL = {"speed": 5.0, "second_speed": 2.5, "retract": 5.0, "distance": 255.0}


@pytest.fixture
def probe_machine(machine, monkeypatch):
    import services.Probing as probing

    def dispatch(line, ack_timeout=1.0):
        machine.calls.append(("mdi", line))
        if "G38.2" in line:
            machine.stat.probe_tripped = True
        return None

    monkeypatch.setattr(probing, "dispatch_mdi", dispatch)
    machine.stat.probe_tripped = False
    machine.stat.probe_val = 0

    def service(override=None):
        s = machine.service(override)
        s._config.payload["z_virtual_endstop"] = VIRTUAL
        return s

    machine.vservice = service
    return machine


def test_virtual_z_is_a_probe_move_then_homed_in_place(probe_machine):
    _run(probe_machine.vservice({"gcode": "G28 Z", "axes": "z"}))
    calls = [c for c in probe_machine.calls if c[0] in ("mdi", "home", "unhome")]
    assert calls == [
        ("unhome", 3), ("mdi", "G91"), ("mdi", "G38.2 Z-255.0000 F300.0"), ("mdi", "G0 Z5.0000"),
        ("mdi", "G38.2 Z-10.0000 F150.0"), ("mdi", "G90"), ("home", 3),
    ]
    assert probe_machine.events[-1][1] == "Homing routine finished."


def test_bare_g28_homes_z_last_on_the_probe(probe_machine):
    _run(probe_machine.vservice({"gcode": "G28", "axes": "xyz"}))
    homes = [c for c in probe_machine.calls if c[0] == "home"]
    assert homes == [("home", 0), ("home", 1), ("home", 3)]  # X, Y (gantry), then Z — never home(-1)


def test_probe_already_pressed_lifts_first(probe_machine):
    probe_machine.stat.probe_val = 1
    _run(probe_machine.vservice({"gcode": "G28 Z", "axes": "z"}))
    mdi = [c[1] for c in probe_machine.calls if c[0] == "mdi"]
    assert mdi[:3] == ["G91", "G0 Z5.0000", "G38.2 Z-255.0000 F300.0"]


def test_probe_not_triggering_stops_homing(probe_machine, monkeypatch):
    import services.Probing as probing

    monkeypatch.setattr(probing, "dispatch_mdi", lambda line, ack_timeout=1.0: probe_machine.calls.append(("mdi", line)))
    _run(probe_machine.vservice({"gcode": "G28 Z", "axes": "z"}))
    assert ("home", 3) not in probe_machine.calls
    assert ("mdi", "G90") in probe_machine.calls  # back to absolute either way
    assert "did not trigger" in probe_machine.events[-1][1]


def test_home_buttons_use_the_probe_without_a_routine(probe_machine, monkeypatch):
    from services.AxisService import AxisService

    service = probe_machine.vservice(None)
    monkeypatch.setattr(module, "get_homing_routine_service", lambda: service)
    started = []
    monkeypatch.setattr(service, "start", lambda steps=None: started.append(steps))
    AxisService().home_single_axes("all")
    AxisService().home_single_axes("z")
    assert [s[0].axes for s in started] == [(), ("Z",)]
    assert service.handles("all") and service.handles("z") and not service.handles("x")


def test_program_guard_with_a_virtual_z(probe_machine):
    with pytest.raises(ConflictError):
        probe_machine.vservice(None).require_homed()
