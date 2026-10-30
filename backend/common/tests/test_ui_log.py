"""``core.ui_log``: a UI backend logs into its own file, once."""
from __future__ import annotations

import logging

import pytest

from core.ui_log import setup_ui_logging


@pytest.fixture()
def restore_handlers():
    loggers = [logging.getLogger(""), logging.getLogger("uvicorn")]
    before = [list(lg.handlers) for lg in loggers]
    propagate = loggers[1].propagate
    yield
    loggers[1].propagate = propagate
    for lg, handlers in zip(loggers, before):
        for h in lg.handlers:
            if h not in handlers:
                h.close()
        lg.handlers[:] = handlers


def test_app_and_uvicorn_lines_reach_the_file_once(tmp_path, restore_handlers):
    logging.getLogger("uvicorn").propagate = False  # as uvicorn's LOGGING_CONFIG sets it
    log_file = tmp_path / "logs" / "ui_system.log"
    setup_ui_logging(log_file)
    setup_ui_logging(log_file)  # a re-import must not double the lines

    logging.getLogger("backend.system.main").warning("app line")
    logging.getLogger("uvicorn.error").error("uvicorn line")
    for h in logging.getLogger("").handlers:
        h.flush()

    text = log_file.read_text(encoding="utf-8")
    assert text.count("app line") == 1
    assert "uvicorn line" in text
