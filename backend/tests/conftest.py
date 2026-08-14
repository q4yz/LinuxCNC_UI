"""Shared pytest fixtures for backend unit tests."""

import os
import sys
from pathlib import Path

import pytest

# Make ``backend/`` importable when pytest is invoked from the repo root.
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


@pytest.fixture()
def tmp_data_root(tmp_path: Path) -> Path:
    """Per-test data root for ``SettingsStore``."""
    return tmp_path


@pytest.fixture()
def clean_env(monkeypatch):
    """Strip ``MODULES_ENABLED`` so tests get the default behaviour.

    Also resets the :class:`ToolsService` singleton's in-memory
    spindle state machine so state does not leak between tests. The
    state machine rejects mid-spin direction reversals with a 409;
    without this reset a test that ran ``forward`` would leave the
    spindle in ``forward`` and break a subsequent ``backward`` test.
    """
    monkeypatch.delenv("MODULES_ENABLED", raising=False)
    try:
        from modules.tools.service import get_tools_service
        svc = get_tools_service()
        svc._spindle_state.clear()
    except Exception:
        # Service may not be importable in every test context; the
        # reset is best-effort.
        pass