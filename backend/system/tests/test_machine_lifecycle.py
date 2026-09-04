"""Tests for :class:`MachineLifecycleService` and its
``/api/v1/system/machine`` router.

The service shells out to ``pgrep``/``subprocess.Popen``/``os.kill``
to detect and control the real ``linuxcnc`` process — none of that
is available (or wanted) in CI, so every test here replaces those
three seams with dummies. No real LinuxCNC or hardware is needed,
matching the rest of the system service's test suite.
"""

from __future__ import annotations

import signal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import services.MachineLifecycleService as mls_module
from exceptions import BadRequestError, ConflictError, NotFoundError
from services.MachineLifecycleService import MachineLifecycleService

# --------------------------------------------------------------------- #
# Fixtures                                                                #
# --------------------------------------------------------------------- #


@pytest.fixture()
def isolated_active_dir(monkeypatch, tmp_path):
    """Point ``ACTIVE_DIR`` at an isolated, empty tmp tree.

    ``MachineLifecycleService`` imports ``ACTIVE_DIR`` by name
    (``from domain_file_services.paths import ACTIVE_DIR``), so the
    module-level name inside ``services.MachineLifecycleService`` —
    not ``domain_file_services.paths.ACTIVE_DIR`` — is what
    :meth:`active_ini` / :meth:`status` see.

    ``machine_name()`` goes through a *different*, cached path —
    ``get_active_service()`` — so the module attribute alone isn't
    enough: without also repointing ``domain_file_services.paths``
    and dropping the service cache, a cached ``ActiveFileService``
    from an earlier test (or this repo's own real
    ``machine_config/active/``) leaks into this test's assertions.
    """
    from services import domain_file_services, reset_service_cache

    active = tmp_path / "active"
    active.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(mls_module, "ACTIVE_DIR", active)
    monkeypatch.setattr(domain_file_services.paths, "ACTIVE_DIR", active)
    reset_service_cache()
    yield active
    reset_service_cache()


@pytest.fixture()
def no_processes(monkeypatch):
    """Every ``pgrep`` probe misses — LinuxCNC is not running."""

    def fake_run(cmd, **kwargs):
        return SimpleNamespace(returncode=1, stdout="")

    monkeypatch.setattr(mls_module.subprocess, "run", fake_run)


@pytest.fixture()
def running_process(monkeypatch):
    """``pgrep -x linuxcnc`` reports pid 4242; every other pattern misses."""

    def fake_run(cmd, **kwargs):
        if cmd[:3] == ["pgrep", "-x", "linuxcnc"]:
            return SimpleNamespace(returncode=0, stdout="4242\n")
        return SimpleNamespace(returncode=1, stdout="")

    monkeypatch.setattr(mls_module.subprocess, "run", fake_run)


class _FakePopen:
    """Stand-in for ``subprocess.Popen`` — records the launch command
    and reports whatever exit state the test asks for."""

    last_command: list[str] | None = None

    def __init__(self, command, *, exit_code=None, pid=4242, **_kwargs):
        _FakePopen.last_command = command
        self.pid = pid
        self.returncode = exit_code
        self._exit_code = exit_code

    def poll(self):
        return self._exit_code


def _service() -> MachineLifecycleService:
    return MachineLifecycleService()


def _app() -> FastAPI:
    from routers.machine_lifecycle import router

    app = FastAPI()
    app.include_router(router)
    return app


def _client() -> TestClient:
    return TestClient(_app())


# --------------------------------------------------------------------- #
# Status / detection                                                     #
# --------------------------------------------------------------------- #


def test_status_reports_not_running(no_processes, isolated_active_dir):
    status = _service().status()
    assert status["running"] is False
    assert status["pids"] == []
    assert status["ini_exists"] is False
    assert status["ini_path"] is None


def test_status_reports_running_with_pids(running_process, isolated_active_dir):
    status = _service().status()
    assert status["running"] is True
    assert status["pids"] == [4242]


def test_status_reports_generated_ini(no_processes, isolated_active_dir):
    ini = isolated_active_dir / "machine.ini"
    ini.write_text("[EMC]\n")
    status = _service().status()
    assert status["ini_exists"] is True
    assert status["ini_path"] == str(ini)


# --------------------------------------------------------------------- #
# start()                                                                 #
# --------------------------------------------------------------------- #


def test_start_raises_conflict_when_already_running(running_process, isolated_active_dir):
    with pytest.raises(ConflictError):
        _service().start()


def test_start_raises_not_found_without_generated_ini(no_processes, isolated_active_dir):
    with pytest.raises(NotFoundError):
        _service().start()


def test_start_runs_linuxcnc_with_the_generated_ini(no_processes, isolated_active_dir, monkeypatch, tmp_path):
    ini = isolated_active_dir / "machine.ini"
    ini.write_text("[EMC]\n")

    monkeypatch.setattr(mls_module, "_CONSOLE_LOG", tmp_path / "console.log")
    monkeypatch.setattr(mls_module.time, "sleep", lambda *_: None)
    monkeypatch.delenv("LINUXCNC_START_COMMAND", raising=False)
    monkeypatch.setattr(
        mls_module.subprocess,
        "Popen",
        lambda command, **kwargs: _FakePopen(command, exit_code=None, pid=1234),
    )

    result = _service().start()

    assert _FakePopen.last_command == ["linuxcnc", str(ini)]
    assert result["started_pid"] == 1234


def test_start_honours_command_override(no_processes, isolated_active_dir, monkeypatch, tmp_path):
    ini = isolated_active_dir / "machine.ini"
    ini.write_text("[EMC]\n")

    monkeypatch.setattr(mls_module, "_CONSOLE_LOG", tmp_path / "console.log")
    monkeypatch.setattr(mls_module.time, "sleep", lambda *_: None)
    monkeypatch.setenv("LINUXCNC_START_COMMAND", "xterm -e linuxcnc {ini}")
    monkeypatch.setattr(
        mls_module.subprocess,
        "Popen",
        lambda command, **kwargs: _FakePopen(command, exit_code=None, pid=1234),
    )

    _service().start()

    # Compare piecewise rather than the raw joined string: shlex.split
    # runs in POSIX mode regardless of host OS, so a Windows dev/test
    # machine's backslash path separators get eaten as escape
    # characters here — a test-environment quirk only, since the real
    # deployment target is always Linux (forward-slash paths).
    assert _FakePopen.last_command[:3] == ["xterm", "-e", "linuxcnc"]
    assert _FakePopen.last_command[3].replace("\\", "") == str(ini).replace("\\", "")


def test_start_raises_bad_request_when_process_exits_immediately(
    no_processes, isolated_active_dir, monkeypatch, tmp_path
):
    ini = isolated_active_dir / "machine.ini"
    ini.write_text("[EMC]\n")

    monkeypatch.setattr(mls_module, "_CONSOLE_LOG", tmp_path / "console.log")
    monkeypatch.setattr(mls_module.time, "sleep", lambda *_: None)
    monkeypatch.setattr(
        mls_module.subprocess,
        "Popen",
        lambda command, **kwargs: _FakePopen(command, exit_code=1, pid=1234),
    )

    with pytest.raises(BadRequestError):
        _service().start()


# --------------------------------------------------------------------- #
# stop()                                                                  #
# --------------------------------------------------------------------- #


def test_stop_is_a_noop_when_nothing_running(no_processes, isolated_active_dir, monkeypatch):
    calls = []
    monkeypatch.setattr(mls_module.os, "kill", lambda *a: calls.append(a))

    result = _service().stop()

    assert result["running"] is False
    assert calls == []


def test_stop_sends_sigint_and_succeeds(isolated_active_dir, monkeypatch):
    state = {"alive": True}

    def fake_run(cmd, **kwargs):
        if state["alive"] and cmd[:3] == ["pgrep", "-x", "linuxcnc"]:
            return SimpleNamespace(returncode=0, stdout="4242\n")
        return SimpleNamespace(returncode=1, stdout="")

    killed = []

    def fake_kill(pid, sig):
        killed.append((pid, sig))
        if sig == signal.SIGINT:
            state["alive"] = False

    monkeypatch.setattr(mls_module.subprocess, "run", fake_run)
    monkeypatch.setattr(mls_module.os, "kill", fake_kill)

    result = _service().stop()

    assert killed == [(4242, signal.SIGINT)]
    assert result["running"] is False


@pytest.mark.skipif(not hasattr(signal, "SIGKILL"), reason="SIGKILL is POSIX-only; the deploy target is always Linux")
def test_stop_escalates_to_sigterm_then_sigkill(isolated_active_dir, monkeypatch):
    # Ignores SIGINT and SIGTERM, only "dies" on SIGKILL.
    state = {"alive": True}

    def fake_run(cmd, **kwargs):
        if state["alive"] and cmd[:3] == ["pgrep", "-x", "linuxcnc"]:
            return SimpleNamespace(returncode=0, stdout="4242\n")
        return SimpleNamespace(returncode=1, stdout="")

    killed = []

    def fake_kill(pid, sig):
        killed.append((pid, sig))
        if sig == signal.SIGKILL:
            state["alive"] = False

    monkeypatch.setattr(mls_module.subprocess, "run", fake_run)
    monkeypatch.setattr(mls_module.os, "kill", fake_kill)
    monkeypatch.setattr(mls_module.time, "sleep", lambda *_: None)
    monkeypatch.setattr(mls_module, "_STOP_GRACE_SECONDS", 0.0)

    result = _service().stop(grace_seconds=0.0)

    assert [sig for _, sig in killed] == [signal.SIGINT, signal.SIGTERM, signal.SIGKILL]
    assert result["running"] is False


# --------------------------------------------------------------------- #
# switch()                                                                #
# --------------------------------------------------------------------- #


def _isolated_machine_dirs(monkeypatch, tmp_path, request):
    from services import domain_file_services, reset_service_cache

    mc = tmp_path / "machine_config"
    profiles = mc / "profiles"
    machines = mc / "machines"
    active = mc / "active"
    for d in (profiles, machines, active):
        d.mkdir(parents=True, exist_ok=True)

    paths_mod = domain_file_services.paths
    monkeypatch.setattr(paths_mod, "MACHINE_CONFIG_DIR", mc)
    monkeypatch.setattr(paths_mod, "PROFILES_DIR", profiles)
    monkeypatch.setattr(paths_mod, "MACHINES_DIR", machines)
    monkeypatch.setattr(paths_mod, "ACTIVE_DIR", active)
    monkeypatch.setattr(mls_module, "ACTIVE_DIR", active)
    reset_service_cache()
    # The cached ActiveFileService singleton outlives monkeypatch's own
    # teardown (which only reverts the setattr calls above, not the
    # cache built from them) — without dropping it here too, the next
    # test to call get_active_service() inherits this test's (by then
    # deleted) tmp path instead of a fresh, correctly-pointed instance.
    request.addfinalizer(reset_service_cache)
    return {"machine_config": mc, "profiles": profiles, "machines": machines, "active": active}


def test_switch_raises_not_found_for_unknown_machine(no_processes, monkeypatch, tmp_path, request):
    _isolated_machine_dirs(monkeypatch, tmp_path, request)

    with pytest.raises(NotFoundError):
        _service().switch(machine="no-such-machine", start_machine=False)


def test_switch_without_a_machine_just_returns_status(no_processes, monkeypatch, tmp_path, request):
    """Omitting ``machine`` restarts whatever is already in active/ — no
    deploy step, so it never raises even with nothing generated yet."""
    _isolated_machine_dirs(monkeypatch, tmp_path, request)

    result = _service().switch(machine=None, start_machine=False)
    assert result["running"] is False


def test_switch_deploys_generated_machine_then_reports_status(no_processes, monkeypatch, tmp_path, request):
    dirs = _isolated_machine_dirs(monkeypatch, tmp_path, request)
    machine_dir = dirs["machines"] / "PrintNC" / "configs"
    machine_dir.mkdir(parents=True)
    (machine_dir / "machine.ini").write_text("[EMC]\nMACHINE = PrintNC\n")

    result = _service().switch(machine="PrintNC", start_machine=False)

    assert (dirs["active"] / "machine.ini").exists()
    assert result["ini_exists"] is True


# --------------------------------------------------------------------- #
# Router (HTTP layer)                                                     #
# --------------------------------------------------------------------- #


def test_get_status_endpoint_returns_200(no_processes, isolated_active_dir):
    response = _client().get("/api/v1/system/machine")
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "running": False,
        "pids": [],
        "machine_name": None,
        "ini_path": None,
        "ini_exists": False,
    }


def test_start_endpoint_returns_404_without_generated_ini(no_processes, isolated_active_dir):
    response = _client().post("/api/v1/system/machine/start")
    assert response.status_code == 404


def test_start_endpoint_returns_409_when_already_running(running_process, isolated_active_dir):
    response = _client().post("/api/v1/system/machine/start")
    assert response.status_code == 409


def test_stop_endpoint_returns_200_when_already_stopped(no_processes, isolated_active_dir):
    response = _client().post("/api/v1/system/machine/stop")
    assert response.status_code == 200
    assert response.json()["running"] is False
