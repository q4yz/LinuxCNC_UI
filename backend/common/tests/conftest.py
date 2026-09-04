"""Shared pytest fixtures for the common-library tests.

Makes ``backend/common/`` importable so flat imports like
``from core.settings_store import ...`` resolve.
"""
import sys
from pathlib import Path

import pytest

_COMMON_DIR = Path(__file__).resolve().parents[1]     # backend/common
if str(_COMMON_DIR) not in sys.path:
    sys.path.insert(0, str(_COMMON_DIR))


@pytest.fixture()
def tmp_data_root(tmp_path: Path) -> Path:
    """Per-test data root for ``SettingsStore``."""
    return tmp_path
