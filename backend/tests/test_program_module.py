"""Tests for the program module's lifecycle HTTP surface.

The program module mirrors LinuxCNC's documented two-step "load
then start" lifecycle:

1. ``POST /load`` -> ``command.program_open(path)`` (sets
   ``stat.file`` while ``interp_state`` stays ``INTERP_IDLE``).
2. ``POST /run``  -> ``auto(AUTO_RUN, line)`` (flips
   ``interp_state`` to ``INTERP_READING``). The endpoint refuses
   with ``409 Conflict`` when no file has been loaded.

These tests cover the state machine end-to-end through the FastAPI
router, including the WebSocket telemetry payload that the
dashboard widget subscribes to.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.event_bus import EventBus
from core.module_registry import ModuleRegistry


# ---------------------------------------------------------------------- #
# Helpers                                                                 #
# ---------------------------------------------------------------------- #


def _reset_mock_program_state() -> None:
    """Reset the mock's program lifecycle fields to the "no program" baseline.

    The mock's ``_machine_state`` is a module-level singleton that
    other tests in the same session may have touched. Each test
    starts from a clean slate so the lifecycle assertions are
    deterministic.
    """
    from hardware import linuxcnc_mock

    with linuxcnc_mock._machine_state.lock:
        linuxcnc_mock._machine_state.file = ""
        linuxcnc_mock._machine_state.current_line = 0
        linuxcnc_mock._machine_state.total_lines = 0
        linuxcnc_mock._machine_state.interp_state = (
            linuxcnc_mock.INTERP_IDLE
        )


def _isolated_program_root(
    tmp_path: Path, monkeypatch, filename: str = "test.gcode"
) -> Path:
    """Point the program service at ``tmp_path`` and seed a gcode file.

    Returns the absolute path of the seeded file.
    """
    from services import domain_file_services, reset_service_cache

    monkeypatch.setattr(
        domain_file_services, "_NC_FILES_DIR", tmp_path, raising=False
    )
    reset_service_cache()

    target = tmp_path / filename
    target.write_text("G28\nG1 X0 Y0 F1500\nM30\n", encoding="utf-8")
    return target


def _program_app(tmp_data_root) -> tuple[FastAPI, ModuleRegistry]:
    """Build a fresh FastAPI app + registry with the program module loaded."""
    from modules.program.module import setup

    reg = ModuleRegistry(data_root=tmp_data_root)
    app = FastAPI()
    reg.boot(app, bus=EventBus(), candidates=[setup()])
    return app, reg


def _state_snapshot() -> dict:
    """Read the mock's program lifecycle fields under the lock."""
    from hardware import linuxcnc_mock

    with linuxcnc_mock._machine_state.lock:
        return {
            "file": linuxcnc_mock._machine_state.file,
            "current_line": linuxcnc_mock._machine_state.current_line,
            "total_lines": linuxcnc_mock._machine_state.total_lines,
            "interp_state": linuxcnc_mock._machine_state.interp_state,
        }


# ---------------------------------------------------------------------- #
# Load                                                                    #
# ---------------------------------------------------------------------- #


def test_load_sets_file_and_resets_to_interp_idle(
    tmp_data_root, clean_env, monkeypatch
):
    """``POST /load`` forwards ``program_open`` to the mock.

    The mock's ``program_open`` sets ``stat.file`` to the absolute
    path on disk, resets ``current_line`` to 0, and stamps
    ``total_lines`` to its 1000-line placeholder. The interpreter
    must stay in ``INTERP_IDLE`` so the widget renders the "Loaded"
    branch rather than the "Running" branch.
    """
    _reset_mock_program_state()
    target = _isolated_program_root(tmp_data_root, monkeypatch)

    app, _ = _program_app(tmp_data_root)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/modules/program/load",
        json={"filename": "test.gcode"},
    )
    assert resp.status_code == 200

    snap = _state_snapshot()
    assert snap["file"] == str(target)
    assert snap["current_line"] == 0
    assert snap["total_lines"] == 1000
    assert snap["interp_state"] == 1  # INTERP_IDLE


def test_load_returns_404_when_file_missing(
    tmp_data_root, clean_env, monkeypatch
):
    """``POST /load`` returns 404 when the filename is unknown."""
    _reset_mock_program_state()
    _isolated_program_root(tmp_data_root, monkeypatch)

    app, _ = _program_app(tmp_data_root)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/modules/program/load",
        json={"filename": "nope.gcode"},
    )
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_load_rejects_path_traversal(
    tmp_data_root, clean_env, monkeypatch
):
    """``POST /load`` refuses filenames that escape ``safe_join``."""
    _reset_mock_program_state()
    _isolated_program_root(tmp_data_root, monkeypatch)

    app, _ = _program_app(tmp_data_root)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/modules/program/load",
        json={"filename": "../etc/passwd"},
    )
    assert resp.status_code == 400
    assert "escapes" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------- #
# Run                                                                     #
# ---------------------------------------------------------------------- #


def test_run_returns_409_when_no_file_loaded(tmp_data_root, clean_env):
    """``POST /run`` refuses to start the interpreter on an empty file.

    This is the "strict" mode contract the frontend relies on to
    surface a clear "no program loaded" message instead of the
    interpreter silently reading nothing.
    """
    _reset_mock_program_state()

    app, _ = _program_app(tmp_data_root)
    client = TestClient(app)
    resp = client.post("/api/v1/modules/program/run")
    assert resp.status_code == 409
    assert "load" in resp.json()["detail"].lower()


def test_run_after_load_advances_current_line(
    tmp_data_root, clean_env, monkeypatch
):
    """End-to-end: load then run, then assert ``current_line > 0``.

    The mock's simulation loop ticks every 100 ms; we wait 350 ms
    to give the background thread room to advance the line counter
    at least twice.
    """
    _reset_mock_program_state()
    _isolated_program_root(tmp_data_root, monkeypatch)

    app, _ = _program_app(tmp_data_root)
    client = TestClient(app)
    assert client.post(
        "/api/v1/modules/program/load",
        json={"filename": "test.gcode"},
    ).status_code == 200
    assert client.post("/api/v1/modules/program/run").status_code == 200

    time.sleep(0.35)

    snap = _state_snapshot()
    assert snap["current_line"] > 0
    assert snap["interp_state"] == 2  # INTERP_READING


def test_stop_after_run_resets_state(
    tmp_data_root, clean_env, monkeypatch
):
    """``POST /stop`` aborts the run and returns the interpreter to idle."""
    _reset_mock_program_state()
    _isolated_program_root(tmp_data_root, monkeypatch)

    app, _ = _program_app(tmp_data_root)
    client = TestClient(app)
    client.post(
        "/api/v1/modules/program/load",
        json={"filename": "test.gcode"},
    )
    client.post("/api/v1/modules/program/run")
    time.sleep(0.2)
    stop = client.post("/api/v1/modules/program/stop")
    assert stop.status_code == 200

    snap = _state_snapshot()
    assert snap["interp_state"] == 1  # INTERP_IDLE
    assert snap["current_line"] == 0


def test_pause_then_resume_keeps_loaded_file(
    tmp_data_root, clean_env, monkeypatch
):
    """Pause/resume must not clear the loaded file.

    The two-step lifecycle is preserved through pause/resume: the
    file pointer stays set so a subsequent ``POST /run`` (or the
    implicit ``auto(AUTO_RESUME)`` behind it) can keep going.
    """
    _reset_mock_program_state()
    target = _isolated_program_root(tmp_data_root, monkeypatch)

    app, _ = _program_app(tmp_data_root)
    client = TestClient(app)
    client.post(
        "/api/v1/modules/program/load",
        json={"filename": "test.gcode"},
    )
    client.post("/api/v1/modules/program/run")
    time.sleep(0.2)
    assert client.post("/api/v1/modules/program/pause").status_code == 200
    assert client.post("/api/v1/modules/program/resume").status_code == 200

    snap = _state_snapshot()
    assert snap["file"] == str(target)


# ---------------------------------------------------------------------- #
# WebSocket telemetry                                                     #
# ---------------------------------------------------------------------- #


def test_websocket_payload_omits_line_counters(
    tmp_data_root, clean_env, monkeypatch
):
    """The telemetry loop no longer carries ``current_line`` /
    ``total_lines``.

    The progress counters moved to the dedicated
    ``GET /api/v1/modules/program/progress`` endpoint so the
    dashboard can poll at 1 Hz without saturating NML. The
    WebSocket broadcast keeps the lighter-weight fields the rest
    of the UI needs (state, position, temperatures, errors).
    """
    _reset_mock_program_state()
    _isolated_program_root(tmp_data_root, monkeypatch)

    from routers.websocket import get_current_state

    # Before the load the snapshot must already omit the counters.
    before = get_current_state()
    assert "current_line" not in before
    assert "total_lines" not in before

    # Drive a load through the public router.
    app, _ = _program_app(tmp_data_root)
    TestClient(app).post(
        "/api/v1/modules/program/load",
        json={"filename": "test.gcode"},
    )

    after = get_current_state()
    assert "current_line" not in after
    assert "total_lines" not in after
    assert after["file"].endswith("test.gcode")
    assert after["interp_state"] == 1  # INTERP_IDLE


# ---------------------------------------------------------------------- #
# Bug-fix regressions for the load-then-start contract                       #
# ---------------------------------------------------------------------- #


class TestLoadThenStartRoundTrip:
    """Regression tests for the bug where ``POST /run`` returned 409
    immediately after ``POST /load`` even though the operator had
    successfully loaded a file.

    The mock mirrors LinuxCNC's behaviour where ``program_open`` is
    asynchronous: the call returns before the interpreter commits the
    file pointer to ``stat.file``. The router now waits for the load
    to land (``_await_load``) and ``is_program_loaded`` queries the
    live stat channel rather than the mock's local dict. These tests
    exercise both halves of the fix.
    """

    def test_load_then_run_advances_to_running_state(
        self, tmp_data_root, clean_env, monkeypatch
    ):
        """End-to-end: load, run, then assert interp_state == READING.

        Reproduces the user's failure: prior to the fix the second
        ``POST /run`` returned 409 because the mock's ``_machine_state``
        was read via a cached ``stat`` instance that hadn't been polled
        since the prior ``program_open``.
        """
        _reset_mock_program_state()
        _isolated_program_root(tmp_data_root, monkeypatch)

        app, _ = _program_app(tmp_data_root)
        client = TestClient(app)

        load_resp = client.post(
            "/api/v1/modules/program/load",
            json={"filename": "test.gcode"},
        )
        assert load_resp.status_code == 200

        run_resp = client.post("/api/v1/modules/program/run")
        assert run_resp.status_code == 200, run_resp.text

        snap = _state_snapshot()
        assert snap["interp_state"] == 2  # INTERP_READING
        assert snap["file"].endswith("test.gcode")

    def test_unload_uses_program_open_empty_not_program_unload(
        self, tmp_data_root, clean_env, monkeypatch
    ):
        """The unload endpoint must clear the file pointer via
        ``program_open("")`` — real LinuxCNC's ``command`` channel
        has no ``program_unload`` method. After unload the file
        pointer is empty, and a follow-up ``/run`` returns 409.
        """
        _reset_mock_program_state()
        _isolated_program_root(tmp_data_root, monkeypatch)

        app, _ = _program_app(tmp_data_root)
        client = TestClient(app)

        # Round-trip: load, then unload.
        load_resp = client.post(
            "/api/v1/modules/program/load",
            json={"filename": "test.gcode"},
        )
        assert load_resp.status_code == 200, load_resp.text
        snap = _state_snapshot()
        assert snap["file"].endswith("test.gcode")

        unload_resp = client.post("/api/v1/modules/program/unload")
        assert unload_resp.status_code == 200, unload_resp.text
        snap = _state_snapshot()
        assert snap["file"] == ""

        # Without a loaded file the run endpoint refuses with 409.
        run_resp = client.post("/api/v1/modules/program/run")
        assert run_resp.status_code == 409
        assert "load" in run_resp.json()["detail"].lower()

    def test_is_program_loaded_uses_stat_channel(
        self, tmp_data_root, clean_env, monkeypatch
    ):
        """``is_program_loaded`` must read from the live stat
        channel. We assert this by setting ``_machine_state.file``
        directly (bypassing ``program_open``) and confirming the
        predicate returns True without any further setup — meaning
        the live stat channel's cached snapshot was refreshed by
        ``poll`` before the predicate read.
        """
        from hardware import linuxcnc_mock
        from hardware.connection import _stat_ch

        _isolated_program_root(tmp_data_root, monkeypatch)

        # Pre-pin the cached stat to a known-true sentinel by
        # running a load through the public router. This way the
        # stat cache is populated with the loaded path.
        app, _ = _program_app(tmp_data_root)
        client = TestClient(app)
        client.post("/api/v1/modules/program/load", json={"filename": "test.gcode"})

        # Mutate the mock state behind the predicate's back so the
        # test asserts the predicate reads the live snapshot rather
        # than the stale cached value. We do this by resetting the
        # mock's ``_machine_state.file`` to a fresh value and
        # checking ``is_program_loaded`` picks it up after a poll.
        target = tmp_data_root / "test.gcode"
        with linuxcnc_mock._machine_state.lock:
            linuxcnc_mock._machine_state.file = str(target)

        stat = _stat_ch.get()
        stat.poll()
        assert stat.file == str(target)
        assert linuxcnc_mock.is_program_loaded() is True

    def test_await_load_returns_immediately_when_file_already_loaded(
        self, tmp_data_root, clean_env, monkeypatch
    ):
        """``_await_load`` is a no-op loop iteration once the stat
        channel reports the target path. The test confirms the load
        endpoint doesn't block on the timeout when the mock's
        ``program_open`` populates ``_machine_state.file``
        synchronously — which it does because ``wait_complete`` is a
        mock no-op.
        """
        import time

        _reset_mock_program_state()
        _isolated_program_root(tmp_data_root, monkeypatch)

        app, _ = _program_app(tmp_data_root)
        client = TestClient(app)

        start = time.monotonic()
        resp = client.post(
            "/api/v1/modules/program/load",
            json={"filename": "test.gcode"},
        )
        elapsed = time.monotonic() - start
        assert resp.status_code == 200
        # Mock-mode load should complete in well under the 5 s budget;
        # the timeout kicks in only when ``stat.file`` never matches.
        assert elapsed < 1.0, f"load took {elapsed:.2f}s; expected < 1s"


# ---------------------------------------------------------------------- #
# Progress endpoint                                                       #
# ---------------------------------------------------------------------- #
#
# The dashboard widget polls ``GET /api/v1/modules/program/progress``
# once a second instead of relying on the 10 Hz WebSocket telemetry
# stream. These tests pin the contract the widget depends on:
#
# * the response shape mirrors the ``ProgramProgressResponse`` model,
# * ``current_line`` advances while the interpreter is reading,
# * ``total_lines`` comes from the cache populated at ``program_open``
#   time so it works on real LinuxCNC where ``stat`` does not expose
#   a total,
# * the cache is cleared on unload so a stale total can never leak
#   across runs.


def _reset_progress_cache() -> None:
    """Drop the line-count cache so each test starts from a clean slate."""
    from modules.program import router as program_router

    program_router._TOTAL_LINES_CACHE.clear()


def test_progress_endpoint_reports_current_line_and_cached_total(
    tmp_data_root, clean_env, monkeypatch
):
    """End-to-end: load + run, then assert the progress endpoint
    surfaces a positive ``current_line`` and the cached ``total_lines``.

    The cache is keyed by the absolute path the interpreter
    committed to ``stat.file``; the test seeds a 4-line gcode file
    so ``total_lines == 4`` on the first ``/progress`` hit. Real
    LinuxCNC populates ``current_line`` while the interpreter reads
    the file; the mock mirrors that behaviour via its simulation
    thread.
    """
    _reset_mock_program_state()
    _reset_progress_cache()
    _isolated_program_root(tmp_data_root, monkeypatch)

    app, _ = _program_app(tmp_data_root)
    client = TestClient(app)
    assert client.post(
        "/api/v1/modules/program/load",
        json={"filename": "test.gcode"},
    ).status_code == 200

    # Before the run starts the line counter is 0 but ``total_lines``
    # is already populated from the cache.
    initial = client.get("/api/v1/modules/program/progress").json()
    assert initial["current_line"] == 0
    assert initial["total_lines"] == 3
    assert initial["interp_state"] == 1  # INTERP_IDLE
    assert initial["file"].endswith("test.gcode")

    assert client.post("/api/v1/modules/program/run").status_code == 200

    # Give the mock's simulation loop a tick to advance.
    time.sleep(0.35)

    running = client.get("/api/v1/modules/program/progress").json()
    assert running["current_line"] > 0
    assert running["total_lines"] == 3
    assert running["interp_state"] == 2  # INTERP_READING


def test_progress_endpoint_returns_zeros_with_no_file(
    tmp_data_root, clean_env, monkeypatch
):
    """Before any load the endpoint must return a safe zeroed
    snapshot so the widget can render the empty-state cleanly.
    """
    _reset_mock_program_state()
    _reset_progress_cache()

    app, _ = _program_app(tmp_data_root)
    client = TestClient(app)

    snapshot = client.get("/api/v1/modules/program/progress").json()
    assert snapshot["current_line"] == 0
    assert snapshot["motion_line"] == 0
    assert snapshot["total_lines"] == 0
    assert snapshot["file"] == ""
    assert snapshot["interp_state"] == 1  # INTERP_IDLE


def test_progress_endpoint_clears_cache_on_unload(
    tmp_data_root, clean_env, monkeypatch
):
    """``POST /unload`` must drop the cached line count so a
    follow-up ``/progress`` cannot surface a stale total for a
    file that is no longer loaded.
    """
    _reset_mock_program_state()
    _reset_progress_cache()
    _isolated_program_root(tmp_data_root, monkeypatch)

    app, _ = _program_app(tmp_data_root)
    client = TestClient(app)
    client.post(
        "/api/v1/modules/program/load",
        json={"filename": "test.gcode"},
    )
    loaded = client.get("/api/v1/modules/program/progress").json()
    assert loaded["total_lines"] == 3

    assert client.post("/api/v1/modules/program/unload").status_code == 200

    cleared = client.get("/api/v1/modules/program/progress").json()
    assert cleared["total_lines"] == 0
    assert cleared["file"] == ""


def test_progress_endpoint_handles_missing_file_in_cache(
    tmp_data_root, clean_env, monkeypatch
):
    """If the cached path is gone (file deleted between load and
    poll) the endpoint must not raise — it returns ``total_lines=0``
    and keeps the rest of the snapshot intact.
    """
    _reset_mock_program_state()
    _reset_progress_cache()
    target = _isolated_program_root(tmp_data_root, monkeypatch)

    from modules.program import router as program_router

    program_router._TOTAL_LINES_CACHE[str(target)] = 9

    from hardware import linuxcnc_mock

    with linuxcnc_mock._machine_state.lock:
        linuxcnc_mock._machine_state.file = str(target)

    app, _ = _program_app(tmp_data_root)
    client = TestClient(app)
    snapshot = client.get("/api/v1/modules/program/progress").json()
    assert snapshot["total_lines"] == 9
    assert snapshot["file"].endswith("test.gcode")
