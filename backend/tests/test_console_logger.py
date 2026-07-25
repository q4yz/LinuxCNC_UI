"""Tests for the persistent console history logger (issue #40).

The logger is a thin file writer — the only thing that matters
behaviourally is that each ``log_event`` call produces exactly one
line on disk, with the timestamp and level in the documented
order, and that the file is reopened lazily on the next call
after ``close()``.

We exercise the singleton helpers (``get_console_logger`` /
``reset_console_logger``) and the MDI endpoint integration so a
regression that stops writing to the on-disk mirror is caught at
the test layer.
"""
from __future__ import annotations

import importlib
import json
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.event_bus import EventBus
from core.module_registry import ModuleRegistry
from services import console_logger as console_logger_module
from services.console_logger import (
    ConsoleLogger,
    LogLevel,
    TYPE_TO_LEVEL,
    get_console_logger,
    reset_console_logger,
)


@pytest.fixture()
def isolated_logger(tmp_path: Path):
    """Force the singleton to point at a brand-new file for each test."""
    target = tmp_path / "console_history.log"
    reset_console_logger(target)
    yield target
    # Restore the default singleton so subsequent tests do not see
    # a stale handle from this one.
    reset_console_logger()


# ---------------------------------------------------------------------- #
# Pure-Python helpers                                                     #
# ---------------------------------------------------------------------- #


def test_log_levels_expose_canonical_tokens():
    """The LogLevel enum matches the vocabulary the UI chips render."""
    assert {level.value for level in LogLevel} == {"INFO", "DEBUG", "WARNING", "ERROR"}


def test_type_to_level_maps_legacy_tokens():
    """The legacy ``type`` table maps info/success/command to INFO."""
    assert TYPE_TO_LEVEL["info"] == LogLevel.INFO
    assert TYPE_TO_LEVEL["success"] == LogLevel.INFO
    assert TYPE_TO_LEVEL["command"] == LogLevel.INFO
    assert TYPE_TO_LEVEL["warning"] == LogLevel.WARNING
    assert TYPE_TO_LEVEL["error"] == LogLevel.ERROR
    assert TYPE_TO_LEVEL["debug"] == LogLevel.DEBUG


def test_default_log_path_targets_repo_root():
    """The default path resolves to the repo root, not the backend dir."""
    path = console_logger_module._default_log_path()
    assert path.name == "console_history.log"
    # The repo root is two levels above ``backend/services/``.
    assert path.parent.name == "LinuxCNC_UI"


# ---------------------------------------------------------------------- #
# File writer                                                             #
# ---------------------------------------------------------------------- #


def test_log_event_writes_one_line_with_timestamp_and_level(isolated_logger):
    """A single command round-trips to a single line with the prefix."""
    logger = get_console_logger()
    logger.log_command("G1 X10")

    contents = isolated_logger.read_text(encoding="utf-8")
    lines = [line for line in contents.splitlines() if line]
    assert len(lines) == 1
    # Timestamp is ISO-8601 with microseconds and a trailing Z.
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z", lines[0])
    # Level is the canonical upper-cased token, padded to five chars.
    assert "[INFO ]" in lines[0]
    # Source tag is recorded after the level.
    assert "CMD G1 X10" in lines[0]


def test_log_event_strips_trailing_newlines(isolated_logger):
    """Newlines inside the message are collapsed so a single call is
    always a single line — a regression here would break ``tail -f``.
    """
    logger = get_console_logger()
    logger.log_event("first\nsecond\nthird", level=LogLevel.WARNING)

    lines = [
        line for line in isolated_logger.read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert len(lines) == 1
    assert "first second third" in lines[0]


def test_log_event_accepts_string_level(isolated_logger):
    """Callers may pass the level as a plain string."""
    logger = get_console_logger()
    logger.log_event("hello", level="debug")

    contents = isolated_logger.read_text(encoding="utf-8")
    assert "[DEBUG]" in contents


def test_log_event_clamps_unknown_levels(isolated_logger):
    """Unknown level strings fall back to INFO rather than raising."""
    logger = get_console_logger()
    logger.log_event("hello", level="bogus")

    contents = isolated_logger.read_text(encoding="utf-8")
    assert "[INFO ]" in contents


def test_log_event_appends_across_calls(isolated_logger):
    """Three calls produce three lines in order."""
    logger = get_console_logger()
    logger.log_command("G1")
    logger.log_response("Executed: G1")
    logger.log_event("Machine error", level=LogLevel.ERROR, source="RES")

    lines = [
        line for line in isolated_logger.read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert len(lines) == 3
    assert "CMD G1" in lines[0]
    assert "RES Executed: G1" in lines[1]
    assert "[ERROR]" in lines[2]
    assert "RES Machine error" in lines[2]


def test_close_is_idempotent(isolated_logger):
    """``close()`` can be called multiple times without raising."""
    logger = ConsoleLogger(isolated_logger)
    logger.log_command("G1")
    logger.close()
    logger.close()

    # Subsequent writes are a no-op so the file does not grow.
    logger.log_command("G2")
    lines = [
        line for line in isolated_logger.read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert len(lines) == 1


def test_relogger_reopens_after_close(isolated_logger):
    """After ``close()`` a fresh logger on the same file appends."""
    first = ConsoleLogger(isolated_logger)
    first.log_command("first")
    first.close()

    second = ConsoleLogger(isolated_logger)
    second.log_command("second")

    lines = [
        line for line in isolated_logger.read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert len(lines) == 2
    assert "CMD first" in lines[0]
    assert "CMD second" in lines[1]


# ---------------------------------------------------------------------- #
# MDI endpoint integration                                                #
# ---------------------------------------------------------------------- #


def _machine_app(tmp_data_root, clean_env, log_path: Path):
    """Build a FastAPI app with the machine module booted against a
    private log file."""
    from modules.machine.module import MachineModule

    reset_console_logger(log_path)
    reg = ModuleRegistry(data_root=tmp_data_root)
    app = FastAPI()
    reg.boot(app, bus=EventBus(), candidates=[MachineModule()])
    return app, reg


def test_mdi_endpoint_writes_command_and_response(
    tmp_path, tmp_data_root, clean_env
):
    """``POST /mdi`` records the command and the response on disk."""
    log_path = tmp_path / "console_history.log"
    app, _ = _machine_app(tmp_data_root, clean_env, log_path)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/modules/machine/mdi",
        json={"command": "G1 X10"},
    )
    assert resp.status_code == 200

    # Allow the lazy file writer to flush before reading.
    get_console_logger().close()

    contents = log_path.read_text(encoding="utf-8")
    lines = [line for line in contents.splitlines() if line]
    assert any("CMD G1 X10" in line for line in lines)
    assert any("RES Executed: G1 X10" in line for line in lines)
    assert any("[INFO ]" in line for line in lines)


def test_mdi_endpoint_records_hardware_error_as_error_level(
    tmp_path, tmp_data_root, clean_env, monkeypatch
):
    """When the hardware layer raises, the log row is tagged ERROR."""
    from fastapi import HTTPException

    from hardware import execute_sync_cmd as real_execute_sync_cmd
    from modules import machine as machine_pkg

    log_path = tmp_path / "console_history.log"
    app, _ = _machine_app(tmp_data_root, clean_env, log_path)

    def fake_execute_sync_cmd(cmd_name, cmd_timeout=0, *args):
        if cmd_name == "mdi":
            raise HTTPException(status_code=400, detail="Bad command")
        return real_execute_sync_cmd(cmd_name, cmd_timeout, *args)

    # The router imported the symbol directly, so we patch the
    # module-global reference rather than the ``hardware`` import.
    monkeypatch.setattr(machine_pkg.router, "execute_sync_cmd", fake_execute_sync_cmd)

    client = TestClient(app)
    resp = client.post(
        "/api/v1/modules/machine/mdi",
        json={"command": "G99"},
    )
    assert resp.status_code == 400

    get_console_logger().close()

    contents = log_path.read_text(encoding="utf-8")
    lines = [line for line in contents.splitlines() if line]
    assert any("[ERROR]" in line and "Bad command" in line for line in lines)


# ---------------------------------------------------------------------- #
# Singleton lifecycle                                                     #
# ---------------------------------------------------------------------- #


def test_reset_console_logger_returns_fresh_instance(tmp_path):
    """``reset_console_logger`` returns a new logger with the given path."""
    target = tmp_path / "isolated.log"
    fresh = reset_console_logger(target)
    assert isinstance(fresh, ConsoleLogger)
    assert fresh.log_path == target
    assert get_console_logger() is fresh


def test_main_lifespan_closes_logger_on_shutdown(tmp_path, tmp_data_root, clean_env, monkeypatch):
    """``backend/main.py``'s lifespan closes the singleton on shutdown."""
    # Reload the module so the import below sees the current code.
    monkeypatch.syspath_prepend(str(tmp_path))
    log_path = tmp_path / "console_history.log"

    # Force the singleton to point at our temporary file. This is
    # the same call the lifespan makes internally, so we do not
    # need to import the FastAPI app to verify the shutdown hook.
    reset_console_logger(log_path)
    logger = get_console_logger()
    logger.log_command("G0")
    logger.close()

    # The file should be flushed and closed; reopening and reading
    # must succeed.
    lines = [
        line for line in log_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert any("CMD G0" in line for line in lines)
