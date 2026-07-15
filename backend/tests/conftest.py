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
    """Strip ``MODULES_ENABLED`` so tests get the default behaviour."""
    monkeypatch.delenv("MODULES_ENABLED", raising=False)