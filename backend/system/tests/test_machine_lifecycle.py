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
from pathlib import Path
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
def isolated_logs(monkeypatch, tmp_path):
    """Point every log source :class:`MachineLifecycleService` reads
    at an isolated tmp tree — otherwise ``console_log()`` would also
    pick up whatever real ``~/linuxcnc_print.txt`` /
    ``~/linuxcnc_debug.txt`` happen to exist in the test-running
    machine's actual home directory, making these tests non-hermetic.
    """
    console = tmp_path / "console.log"
    print_log = tmp_path / "linuxcnc_print.txt"
    debug_log = tmp_path / "linuxcnc_debug.txt"
    monkeypatch.setattr(mls_module, "_CONSOLE_LOG", console)
    monkeypatch.setattr(mls_module, "_HOME_PRINT_LOG", print_log)
    monkeypatch.setattr(mls_module, "_HOME_DEBUG_LOG", debug_log)
    return {"console": console, "print": print_log, "debug": debug_log}


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


# --------------------------------------------------------------------- #
# Default machine (persisted selection)                                  #
# --------------------------------------------------------------------- #


@pytest.fixture()
def isolated_machines_root(monkeypatch, tmp_path, request):
    """Point ``MACHINE_CONFIG_DIR`` / ``MACHINES_DIR`` at an isolated
    tmp tree with a ``machines/`` folder.

    The default-machine helpers read ``MACHINE_CONFIG_DIR`` at call
    time (import inside the method), so patching the paths module is
    enough. The machine file service is a cached singleton, so the
    cache must be dropped both before and after — same pattern as
    :func:`isolated_active_dir`.
    """
    from services import domain_file_services, reset_service_cache

    mc = tmp_path / "machine_config"
    machines = mc / "machines"
    machines.mkdir(parents=True)
    paths_mod = domain_file_services.paths
    monkeypatch.setattr(paths_mod, "MACHINE_CONFIG_DIR", mc)
    monkeypatch.setattr(paths_mod, "MACHINES_DIR", machines)
    reset_service_cache()
    request.addfinalizer(reset_service_cache)
    return {"machine_config": mc, "machines": machines}


def _make_machine(machines_root, name):
    """Create ``machines/<name>/config/machine.ini`` and return the ini."""
    cfg = machines_root / name / "config"
    cfg.mkdir(parents=True)
    ini = cfg / "machine.ini"
    ini.write_text("[EMC]\n")
    return ini


def test_default_machine_is_none_until_set(no_processes, isolated_machines_root):
    assert _service().default_machine() is None
    assert _service().default_ini() is None
    status = _service().status()
    assert status["default_machine"] is None
    assert status["ini_exists"] is False


def test_set_default_machine_persists_and_validates(no_processes, isolated_machines_root):
    ini = _make_machine(isolated_machines_root["machines"], "PrintNC")

    returned = _service().set_default_machine("PrintNC")

    assert returned == ini
    assert _service().default_machine() == "PrintNC"
    assert _service().default_ini() == ini
    # The selection survives on disk (a fresh service instance sees it).
    assert _service().default_machine() == "PrintNC"

    status = _service().status()
    assert status["default_machine"] == "PrintNC"
    # Deprecated alias kept in lockstep for the generated model.
    assert status["machine_name"] == "PrintNC"
    assert status["ini_path"] == str(ini)
    assert status["ini_exists"] is True


def test_machine_ini_accepts_the_generated_configs_layout(
    no_processes, isolated_machines_root, monkeypatch, tmp_path
):
    """Real generator output: ``machines/<name>/configs/machine.ini``
    (plural ``configs/``) must resolve even though the manual
    ``config/`` convention is tried first.
    """
    cfg = isolated_machines_root["machines"] / "printnc" / "configs"
    cfg.mkdir(parents=True)
    ini = cfg / "machine.ini"
    ini.write_text("[EMC]\n")

    assert _service().machine_ini("printnc") == ini

    _service().set_default_machine("printnc")
    assert _service().default_ini() == ini
    status = _service().status()
    assert status["default_machine"] == "printnc"
    assert status["ini_exists"] is True


def test_set_default_machine_rejects_missing_ini(no_processes, isolated_machines_root):
    (isolated_machines_root["machines"] / "Empty").mkdir()
    with pytest.raises(NotFoundError):
        _service().set_default_machine("Empty")
    assert _service().default_machine() is None


def test_machine_ini_rejects_path_escape(no_processes, isolated_machines_root):
    with pytest.raises(BadRequestError):
        _service().machine_ini("../outside")


# --------------------------------------------------------------------- #
# start()                                                                 #
# --------------------------------------------------------------------- #


def test_start_raises_conflict_when_already_running(running_process, isolated_active_dir):
    with pytest.raises(ConflictError):
        _service().start()


def test_start_raises_not_found_without_default_machine(no_processes, isolated_machines_root):
    with pytest.raises(NotFoundError):
        _service().start()


def _patch_launch(monkeypatch, tmp_path, exit_code=None):
    """Replace the real process launch with ``_FakePopen``.

    ``shutil.which("stdbuf")`` is pinned to "not found" so the
    launch-command assertions below see the bare command — CI runs
    on ubuntu-latest, where the real ``stdbuf`` *is* on PATH, which
    would otherwise silently prepend ``["stdbuf", "-oL", "-eL"]`` and
    break every exact-match assertion here. The prefixing itself is
    covered separately in ``test_build_command_prefers_stdbuf_when_available``.
    """
    monkeypatch.setattr(mls_module, "_CONSOLE_LOG", tmp_path / "console.log")
    monkeypatch.setattr(mls_module, "_HOME_PRINT_LOG", tmp_path / "linuxcnc_print.txt")
    monkeypatch.setattr(mls_module, "_HOME_DEBUG_LOG", tmp_path / "linuxcnc_debug.txt")
    monkeypatch.setattr(mls_module.time, "sleep", lambda *_: None)
    monkeypatch.delenv("LINUXCNC_START_COMMAND", raising=False)
    monkeypatch.setattr(mls_module.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        mls_module.subprocess,
        "Popen",
        lambda command, **kwargs: _FakePopen(command, exit_code=exit_code, pid=1234),
    )


def test_start_persists_and_launches_the_requested_machine(
    no_processes, isolated_machines_root, monkeypatch, tmp_path
):
    ini = _make_machine(isolated_machines_root["machines"], "PrintNC")
    _patch_launch(monkeypatch, tmp_path)

    result = _service().start(machine="PrintNC")

    # start implies main: the selection is persisted and the INI at
    # machines/<machine>/config/machine.ini is what gets launched.
    assert _service().default_machine() == "PrintNC"
    assert _FakePopen.last_command == ["linuxcnc", str(ini)]
    assert result["started_pid"] == 1234
    assert result["default_machine"] == "PrintNC"


def test_start_without_machine_launches_the_default(
    no_processes, isolated_machines_root, monkeypatch, tmp_path
):
    ini = _make_machine(isolated_machines_root["machines"], "OtherCNC")
    _service().set_default_machine("OtherCNC")
    _patch_launch(monkeypatch, tmp_path)

    result = _service().start()

    assert _FakePopen.last_command == ["linuxcnc", str(ini)]
    assert result["started_pid"] == 1234


def test_start_honours_command_override(
    no_processes, isolated_machines_root, monkeypatch, tmp_path
):
    ini = _make_machine(isolated_machines_root["machines"], "PrintNC")
    _service().set_default_machine("PrintNC")

    monkeypatch.setattr(mls_module, "_CONSOLE_LOG", tmp_path / "console.log")
    monkeypatch.setattr(mls_module.time, "sleep", lambda *_: None)
    monkeypatch.setenv("LINUXCNC_START_COMMAND", "xterm -e linuxcnc {ini}")
    monkeypatch.setattr(mls_module.shutil, "which", lambda name: None)
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


def test_build_command_prefers_stdbuf_when_available(monkeypatch):
    """LinuxCNC's own stdio is fully block-buffered once redirected
    to our log file, so a hard abort (realtime error, bad HAL/INI
    parse) can lose its entire error message — the operator still
    sees it in LinuxCNC's on-screen dialog (X11, not stdio) while the
    log stays empty. ``stdbuf -oL -eL`` forces line buffering so
    every line lands in the log as it's printed, crash or not."""
    ini = Path("PrintNC") / "config" / "machine.ini"
    monkeypatch.setattr(mls_module.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.delenv("LINUXCNC_START_COMMAND", raising=False)

    command = _service()._build_command(ini)

    assert command[:3] == ["stdbuf", "-oL", "-eL"]
    assert command[3:] == ["linuxcnc", str(ini)]


def test_build_command_skips_stdbuf_when_not_on_path(monkeypatch):
    ini = Path("PrintNC") / "config" / "machine.ini"
    monkeypatch.setattr(mls_module.shutil, "which", lambda name: None)
    monkeypatch.delenv("LINUXCNC_START_COMMAND", raising=False)

    command = _service()._build_command(ini)

    assert command == ["linuxcnc", str(ini)]


def test_build_command_prefixes_stdbuf_before_an_override_too(monkeypatch):
    ini = Path("PrintNC") / "config" / "machine.ini"
    monkeypatch.setattr(mls_module.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setenv("LINUXCNC_START_COMMAND", "xterm -e linuxcnc {ini}")

    command = _service()._build_command(ini)

    # See test_start_honours_command_override: shlex.split runs in
    # POSIX mode regardless of host OS, so a Windows dev/test
    # machine's backslash path separators get eaten as escape
    # characters — a test-environment quirk only.
    assert command[:5] == ["stdbuf", "-oL", "-eL", "xterm", "-e"]
    assert command[5] == "linuxcnc"
    assert command[6].replace("\\", "") == str(ini).replace("\\", "")


def test_start_raises_bad_request_when_process_exits_immediately(
    no_processes, isolated_machines_root, monkeypatch, tmp_path
):
    _make_machine(isolated_machines_root["machines"], "PrintNC")
    _service().set_default_machine("PrintNC")
    _patch_launch(monkeypatch, tmp_path, exit_code=1)

    with pytest.raises(BadRequestError):
        _service().start()


def test_start_crash_error_includes_console_log_tail(
    no_processes, isolated_machines_root, monkeypatch, tmp_path
):
    """The immediate-crash error is the most common "why won't it
    start" case — the console log's tail rides along in the message
    so the UI shows the real problem without a follow-up request."""
    _make_machine(isolated_machines_root["machines"], "PrintNC")
    _service().set_default_machine("PrintNC")
    _patch_launch(monkeypatch, tmp_path, exit_code=1)

    console_log = tmp_path / "console.log"
    console_log.write_text("realtime delay error: max is 63684, expected < 1000\n", encoding="utf-8")

    with pytest.raises(BadRequestError) as excinfo:
        _service().start()

    assert "realtime delay error" in str(excinfo.value)


# --------------------------------------------------------------------- #
# console_log()                                                          #
# --------------------------------------------------------------------- #


def test_console_log_reports_missing_file(isolated_logs):
    result = _service().console_log()

    assert result["exists"] is False
    assert result["log"] == ""


def test_console_log_returns_the_requested_tail(isolated_logs):
    isolated_logs["console"].write_text(
        "\n".join(f"line {i}" for i in range(1, 11)) + "\n", encoding="utf-8"
    )

    result = _service().console_log(lines=3)

    assert result["exists"] is True
    assert result["path"] == str(isolated_logs["console"])
    assert "line 8\nline 9\nline 10" in result["log"]
    assert "logs/linuxcnc_console.log" in result["log"]


def test_console_log_merges_linuxcncs_own_redirect_targets(isolated_logs):
    """LinuxCNC redirects its own stdout/stderr to
    ``~/linuxcnc_print.txt`` / ``~/linuxcnc_debug.txt`` the moment it
    isn't talking to an interactive terminal — true for every
    detached session we spawn — so our tee alone can stay empty while
    the real crash text lands in one of these instead. Both must
    surface even when our own tee has nothing."""
    isolated_logs["debug"].write_text(
        "Error: INI file section [AXIS_0] missing required key STEPGEN_MAXVEL\n",
        encoding="utf-8",
    )

    result = _service().console_log()

    assert result["exists"] is True
    assert "STEPGEN_MAXVEL" in result["log"]
    assert "linuxcnc_debug.txt" in result["log"]


def test_console_log_labels_each_present_source(isolated_logs):
    isolated_logs["console"].write_text("tee output\n", encoding="utf-8")
    isolated_logs["print"].write_text("print output\n", encoding="utf-8")

    result = _service().console_log()

    assert "tee output" in result["log"]
    assert "print output" in result["log"]
    assert "linuxcnc_console.log" in result["log"]
    assert "linuxcnc_print.txt" in result["log"]
    # The debug log was never written — it must not appear as a
    # confusing empty section.
    assert "linuxcnc_debug.txt" not in result["log"]


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

    # The deploy itself still lands in active/ (legacy switch flow).
    assert (dirs["active"] / "machine.ini").exists()
    # But status() reports the *default machine*, not active/ — the
    # default was never set in this test, so no INI is reported.
    assert result["ini_exists"] is False


# --------------------------------------------------------------------- #
# Router (HTTP layer)                                                     #
# --------------------------------------------------------------------- #


def test_get_status_endpoint_returns_200(no_processes, isolated_machines_root):
    response = _client().get("/api/v1/system/machine")
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "running": False,
        "pids": [],
        "machine_name": None,
        "default_machine": None,
        "ini_path": None,
        "ini_exists": False,
    }


def test_start_endpoint_returns_404_without_default_machine(no_processes, isolated_machines_root):
    response = _client().post("/api/v1/system/machine/start")
    assert response.status_code == 404


def test_start_endpoint_returns_409_when_already_running(running_process, isolated_active_dir):
    response = _client().post("/api/v1/system/machine/start")
    assert response.status_code == 409


def test_start_endpoint_with_machine_body_persists_default(
    no_processes, isolated_machines_root, monkeypatch, tmp_path
):
    ini = _make_machine(isolated_machines_root["machines"], "PrintNC")
    _patch_launch(monkeypatch, tmp_path)

    response = _client().post(
        "/api/v1/system/machine/start",
        json={"machine": "PrintNC"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["started_pid"] == 1234
    assert body["default_machine"] == "PrintNC"
    assert body["ini_path"] == str(ini)
    assert _service().default_machine() == "PrintNC"


def test_set_default_endpoint_persists_without_starting(
    no_processes, isolated_machines_root
):
    _make_machine(isolated_machines_root["machines"], "PrintNC")

    response = _client().post(
        "/api/v1/system/machine/default",
        json={"machine": "PrintNC"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["default_machine"] == "PrintNC"
    assert body["running"] is False
    # Selection persisted, nothing launched.
    assert _service().default_machine() == "PrintNC"


def test_set_default_endpoint_returns_404_for_missing_ini(
    no_processes, isolated_machines_root
):
    (isolated_machines_root["machines"] / "Empty").mkdir()
    response = _client().post(
        "/api/v1/system/machine/default",
        json={"machine": "Empty"},
    )
    assert response.status_code == 404


def test_stop_endpoint_returns_200_when_already_stopped(no_processes, isolated_active_dir):
    response = _client().post("/api/v1/system/machine/stop")
    assert response.status_code == 200
    assert response.json()["running"] is False


def test_log_endpoint_returns_the_tail(isolated_logs):
    isolated_logs["console"].write_text("boom: config error\n", encoding="utf-8")

    response = _client().get("/api/v1/system/machine/log")

    assert response.status_code == 200
    body = response.json()
    assert body["exists"] is True
    assert "boom: config error" in body["log"]


def test_log_endpoint_reports_missing_file(isolated_logs):
    response = _client().get("/api/v1/system/machine/log")

    assert response.status_code == 200
    body = response.json()
    assert body["exists"] is False
    assert body["log"] == ""
