"""Tests for ``POST /api/v1/modules/macros/{name}/start`` (machine backend).

The execution half of the macros domain moved into the machine
backend's :class:`MacroExecutionService` during the two-service
split. These tests port the legacy ``TestStartMacroEndpoint`` suite
from the former monolithic macros module to the new service API:

* macros are seeded into an isolated ``MacroFileService`` root
  (no HTTP CRUD surface exists on this side);
* ``dispatch_mdi`` / ``get_stat_channel`` are patched on the
  ``MacroExecutionService`` module so no real NML channel is needed.
"""
from __future__ import annotations

from tests._module_app_factory import build_module_app

from pathlib import Path

from fastapi.testclient import TestClient

from domain_file_services import MacroFileService, MCodeFileService


def _macros_exec_app(tmp_data_root):
    """Build a fresh FastAPI app with the macro-start router mounted."""
    return build_module_app("macros", tmp_data_root)


class _Setup:
    """Common patch scaffolding for the start-endpoint tests."""

    def __init__(self, tmp_data_root, monkeypatch, root_name="macros_for_exec"):
        import services.MacroExecutionService as exec_module

        self.exec_module = exec_module

        isolated_root = tmp_data_root / root_name
        isolated_root.mkdir(parents=True, exist_ok=True)
        self.macro_service = MacroFileService(isolated_root)
        self.mcode_service = MCodeFileService(tmp_data_root / (root_name + "_m"))

        monkeypatch.setattr(
            exec_module, "get_macro_service", lambda root=None: self.macro_service
        )
        monkeypatch.setattr(
            exec_module, "get_mcode_service", lambda root=None: self.mcode_service
        )

        self.calls: list[str] = []
        monkeypatch.setattr(exec_module, "dispatch_mdi", self._fake_execute)
        monkeypatch.setattr(exec_module, "_IDLE_POLL_S", 0)

    def _fake_execute(self, line, ack_timeout=1.0):
        self.calls.append(line)
        return None

    def set_stat(self, monkeypatch, task_state, estop=False):
        """Patch ``get_stat_channel`` with a minimal fake stat object."""
        from hardware.Connection import MachineState

        if task_state is None:
            task_state = MachineState.ON.value
        fake_stat = type(
            "Stat",
            (),
            {
                "poll": lambda self: None,
                "estop": estop,
                "task_state": task_state,
            },
        )()
        monkeypatch.setattr(self.exec_module, "get_stat_channel", lambda: fake_stat)
        return fake_stat

    def join(self):
        """Wait for the background macro worker to finish."""
        self.exec_module.get_macro_execution_service().join(timeout=5)

    def client(self, tmp_data_root):
        return TestClient(_macros_exec_app(tmp_data_root))


class TestStartMacroEndpoint:
    """Dispatch-path tests for the machine-backend macro execution."""

    def test_macro_kind_dispatches_every_static_line_via_mdi(
        self, tmp_data_root, clean_env, monkeypatch
    ):
        setup = _Setup(tmp_data_root, monkeypatch)
        setup.set_stat(monkeypatch, task_state=None)
        client = setup.client(tmp_data_root)

        payload = (
            "G91\n"                       # static line 1
            "G1 X10 F1000\n"              # static line 2
            "{ log('between blocks') }\n" # python block (skipped)
            "G90\n"                       # static line 3
        )
        (setup.macro_service.root / "spindle_warmup.macro").write_text(
            payload, encoding="utf-8"
        )

        resp = client.post("/api/v1/modules/macros/spindle_warmup/start?kind=macro")
        assert resp.status_code == 202
        setup.join()
        assert setup.calls == ["G91", "G1 X10 F1000", "G90"]

    def test_macro_kind_skips_python_blocks(
        self, tmp_data_root, clean_env, monkeypatch
    ):
        setup = _Setup(tmp_data_root, monkeypatch)
        setup.set_stat(monkeypatch, task_state=None)
        client = setup.client(tmp_data_root)

        (setup.macro_service.root / "skippy.macro").write_text(
            "{ first }\n{ second }\n", encoding="utf-8"
        )

        resp = client.post("/api/v1/modules/macros/skippy/start?kind=macro")
        assert resp.status_code == 202
        setup.join()
        assert setup.calls == []

    def test_macro_kind_aborts_on_mid_run_estop(
        self, tmp_data_root, clean_env, monkeypatch
    ):
        setup = _Setup(tmp_data_root, monkeypatch)
        fake_stat = setup.set_stat(monkeypatch, task_state=None)
        client = setup.client(tmp_data_root)

        (setup.macro_service.root / "aborty.macro").write_text(
            "G0 X1\nG0 X2\nG0 X3\nG0 X4\n", encoding="utf-8"
        )

        # Flip estop on the second dispatch — the service re-polls
        # ``stat`` before every line, so line 3 must never dispatch.
        estop_flag = {"value": False}

        def poll(_self):
            _self.estop = estop_flag["value"]

        fake_stat.poll = poll.__get__(fake_stat)

        real_execute = setup._fake_execute

        def execute_then_flip(line, ack_timeout=1.0):
            result = real_execute(line, ack_timeout)
            if len(setup.calls) == 2:
                estop_flag["value"] = True
            return result

        monkeypatch.setattr(setup.exec_module, "dispatch_mdi", execute_then_flip)

        resp = client.post("/api/v1/modules/macros/aborty/start?kind=macro")
        assert resp.status_code == 202
        setup.join()
        assert setup.calls == ["G0 X1", "G0 X2"]

    def test_macro_waits_for_interpreter_idle_before_next_line(
        self, tmp_data_root, clean_env, monkeypatch
    ):
        """A line is only followed by the next once ``interp_state`` is
        idle again — the wait happens by polling ``stat``, not inside
        the command lock."""
        setup = _Setup(tmp_data_root, monkeypatch)
        fake_stat = setup.set_stat(monkeypatch, task_state=None)
        client = setup.client(tmp_data_root)

        (setup.macro_service.root / "slow.macro").write_text(
            "G1 X10\nG1 X20\n", encoding="utf-8"
        )

        busy_polls = {"left": 0}
        seen_while_busy: list[list[str]] = []

        def dispatch(line, ack_timeout=1.0):
            setup.calls.append(line)
            busy_polls["left"] = 3
            return None

        def poll(_self):
            if busy_polls["left"] > 0:
                busy_polls["left"] -= 1
                _self.interp_state = 2  # INTERP_READING
                seen_while_busy.append(list(setup.calls))
            else:
                _self.interp_state = 1  # INTERP_IDLE

        fake_stat.poll = poll.__get__(fake_stat)
        monkeypatch.setattr(setup.exec_module, "dispatch_mdi", dispatch)

        resp = client.post("/api/v1/modules/macros/slow/start?kind=macro")
        assert resp.status_code == 202
        setup.join()
        assert setup.calls == ["G1 X10", "G1 X20"]
        # While the first move was still running, the second line
        # had not been dispatched yet.
        assert ["G1 X10"] in seen_while_busy

    def test_macro_aborts_when_mode_leaves_mdi(
        self, tmp_data_root, clean_env, monkeypatch
    ):
        from hardware.Connection import MachineMode

        setup = _Setup(tmp_data_root, monkeypatch)
        fake_stat = setup.set_stat(monkeypatch, task_state=None)
        client = setup.client(tmp_data_root)

        (setup.macro_service.root / "moded.macro").write_text(
            "G0 X1\nG0 X2\n", encoding="utf-8"
        )
        fake_stat.task_mode = MachineMode.MANUAL

        resp = client.post("/api/v1/modules/macros/moded/start?kind=macro")
        assert resp.status_code == 202
        setup.join()
        assert setup.calls == ["G0 X1"]

    def test_start_returns_before_the_macro_finishes(
        self, tmp_data_root, clean_env, monkeypatch
    ):
        """The request answers 202 while the worker is still dispatching,
        and a second start meanwhile is refused with 409."""
        import threading

        setup = _Setup(tmp_data_root, monkeypatch)
        setup.set_stat(monkeypatch, task_state=None)
        client = setup.client(tmp_data_root)

        (setup.macro_service.root / "long.macro").write_text(
            "G1 X10\nG1 X20\n", encoding="utf-8"
        )

        release = threading.Event()

        def blocking_dispatch(line, ack_timeout=1.0):
            setup.calls.append(line)
            release.wait(timeout=5)
            return None

        monkeypatch.setattr(setup.exec_module, "dispatch_mdi", blocking_dispatch)

        try:
            resp = client.post("/api/v1/modules/macros/long/start?kind=macro")
            assert resp.status_code == 202

            again = client.post("/api/v1/modules/macros/long/start?kind=macro")
            assert again.status_code == 409
        finally:
            release.set()
            setup.join()

        assert setup.calls == ["G1 X10", "G1 X20"]

    def test_ngc_kind_dispatches_subroutine_call(
        self, tmp_data_root, clean_env, monkeypatch
    ):
        setup = _Setup(tmp_data_root, monkeypatch)
        setup.set_stat(monkeypatch, task_state=None)
        client = setup.client(tmp_data_root)

        (setup.macro_service.root / "coolant.ngc").write_text(
            "O<coolant> sub\nM8\nO<coolant> endsub\n", encoding="utf-8"
        )

        resp = client.post("/api/v1/modules/macros/coolant/start?kind=ngc")
        assert resp.status_code == 202
        setup.join()
        assert setup.calls == ["o<coolant> call"]

    def test_ngc_args_become_positional_call_parameters(
        self, tmp_data_root, clean_env, monkeypatch
    ):
        setup = _Setup(tmp_data_root, monkeypatch)
        setup.set_stat(monkeypatch, task_state=None)
        client = setup.client(tmp_data_root)

        (setup.macro_service.root / "probe_circle_inside.ngc").write_text(
            "O<probe_circle_inside> sub\nO<probe_circle_inside> endsub\n", encoding="utf-8"
        )

        resp = client.post(
            "/api/v1/modules/macros/probe_circle_inside/start",
            params=[("kind", "ngc"), ("args", "4"), ("args", "12.5"), ("args", "-0.0000001"), ("args", "100")],
        )
        assert resp.status_code == 202
        setup.join()
        # Fixed-point only (no exponent G-code can't parse), trailing
        # zeros dropped, a value that rounds to zero written as 0.
        assert setup.calls == ["o<probe_circle_inside> call [4] [12.5] [0] [100]"]

    def test_non_numeric_arg_is_rejected_with_422(
        self, tmp_data_root, clean_env, monkeypatch
    ):
        setup = _Setup(tmp_data_root, monkeypatch)
        setup.set_stat(monkeypatch, task_state=None)
        client = setup.client(tmp_data_root)

        (setup.macro_service.root / "evil.ngc").write_text("O<evil> sub\nO<evil> endsub\n", encoding="utf-8")

        resp = client.post(
            "/api/v1/modules/macros/evil/start",
            params=[("kind", "ngc"), ("args", "1] M2 [")],
        )
        assert resp.status_code == 422
        assert setup.calls == []

    def test_non_finite_arg_is_rejected_with_400(
        self, tmp_data_root, clean_env, monkeypatch
    ):
        setup = _Setup(tmp_data_root, monkeypatch)
        setup.set_stat(monkeypatch, task_state=None)
        client = setup.client(tmp_data_root)

        (setup.macro_service.root / "inf.ngc").write_text("O<inf> sub\nO<inf> endsub\n", encoding="utf-8")

        resp = client.post("/api/v1/modules/macros/inf/start", params=[("kind", "ngc"), ("args", "inf")])
        assert resp.status_code in (400, 422)
        assert setup.calls == []

    def test_args_on_a_macro_kind_are_rejected_with_400(
        self, tmp_data_root, clean_env, monkeypatch
    ):
        setup = _Setup(tmp_data_root, monkeypatch)
        setup.set_stat(monkeypatch, task_state=None)
        client = setup.client(tmp_data_root)

        (setup.macro_service.root / "plain.macro").write_text("G0 X1\n", encoding="utf-8")

        resp = client.post("/api/v1/modules/macros/plain/start", params=[("kind", "macro"), ("args", "1")])
        assert resp.status_code == 400
        assert setup.calls == []

    def test_ngc_call_blocks_a_second_start_until_it_finishes(
        self, tmp_data_root, clean_env, monkeypatch
    ):
        """A double-clicked probe cycle must not queue a second probe."""
        import threading

        setup = _Setup(tmp_data_root, monkeypatch)
        setup.set_stat(monkeypatch, task_state=None)
        client = setup.client(tmp_data_root)

        (setup.macro_service.root / "probe.ngc").write_text("O<probe> sub\nO<probe> endsub\n", encoding="utf-8")

        release = threading.Event()

        def blocking_dispatch(line, ack_timeout=1.0):
            setup.calls.append(line)
            release.wait(timeout=5)
            return None

        monkeypatch.setattr(setup.exec_module, "dispatch_mdi", blocking_dispatch)
        try:
            assert client.post("/api/v1/modules/macros/probe/start?kind=ngc").status_code == 202
            assert client.post("/api/v1/modules/macros/probe/start?kind=ngc").status_code == 409
        finally:
            release.set()
            setup.join()
        assert setup.calls == ["o<probe> call"]

    def test_mcode_kind_is_rejected_with_400(
        self, tmp_data_root, clean_env, monkeypatch
    ):
        setup = _Setup(tmp_data_root, monkeypatch)
        setup.set_stat(monkeypatch, task_state=None)
        client = setup.client(tmp_data_root)

        (setup.mcode_service.root).mkdir(parents=True, exist_ok=True)
        (setup.mcode_service.root / "M120").write_text("G4 P1\n", encoding="utf-8")

        resp = client.post("/api/v1/modules/macros/M120/start?kind=mcode")
        assert resp.status_code == 400
        assert "wrap" in resp.json()["detail"].lower()

    def test_pre_flight_estop_returns_400(
        self, tmp_data_root, clean_env, monkeypatch
    ):
        setup = _Setup(tmp_data_root, monkeypatch)
        setup.set_stat(monkeypatch, task_state=None, estop=True)
        client = setup.client(tmp_data_root)

        (setup.macro_service.root / "estop_me.macro").write_text(
            "G0 X0\n", encoding="utf-8"
        )

        resp = client.post("/api/v1/modules/macros/estop_me/start?kind=macro")
        assert resp.status_code == 400
        assert "e-stop" in resp.json()["detail"].lower()

    def test_pre_flight_offline_returns_400(
        self, tmp_data_root, clean_env, monkeypatch
    ):
        setup = _Setup(tmp_data_root, monkeypatch)
        monkeypatch.setattr(setup.exec_module, "get_stat_channel", lambda: None)
        client = setup.client(tmp_data_root)

        (setup.macro_service.root / "offline.macro").write_text(
            "G0 X0\n", encoding="utf-8"
        )

        resp = client.post("/api/v1/modules/macros/offline/start?kind=macro")
        assert resp.status_code == 400
        assert "not running" in resp.json()["detail"].lower()

    def test_missing_macro_returns_404(
        self, tmp_data_root, clean_env, monkeypatch
    ):
        setup = _Setup(tmp_data_root, monkeypatch)
        setup.set_stat(monkeypatch, task_state=None)
        client = setup.client(tmp_data_root)

        resp = client.post("/api/v1/modules/macros/nope/start?kind=macro")
        assert resp.status_code == 404

    def test_invalid_kind_returns_400(
        self, tmp_data_root, clean_env, monkeypatch
    ):
        setup = _Setup(tmp_data_root, monkeypatch)
        setup.set_stat(monkeypatch, task_state=None)
        client = setup.client(tmp_data_root)

        resp = client.post("/api/v1/modules/macros/whatever/start?kind=bogus")
        assert resp.status_code == 400
