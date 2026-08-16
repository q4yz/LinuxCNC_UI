"""Shared pytest fixtures for backend unit tests."""

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

    The spindle direction-conflict check in
    :class:`SpindleDigitalService` is now derived from HAL pin reads
    (``pins.spindle_forward.get_value()`` / ``pins.spindle_reverse.get_value()``)
    rather than a singleton attribute, so per-test reset of the
    service is no longer required. The mock's per-tool telemetry
    buffer (held by :data:`hardware.linuxcnc_mock._machine_state`)
    is reseeded on process start and survives across tests
    intentionally — it is process-global state for the mock driver.
    """
    monkeypatch.delenv("MODULES_ENABLED", raising=False)