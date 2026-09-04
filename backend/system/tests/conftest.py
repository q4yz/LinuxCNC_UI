"""Shared pytest fixtures for the system-service tests.

Makes both the app directory (``backend/system/``) and the shared
library (``backend/common/``) importable, so flat imports like
``from services.X import Y`` and ``from domain_file_services import ...``
resolve inside this suite.
"""
import sys
from pathlib import Path

import pytest

_APP_DIR = Path(__file__).resolve().parents[1]        # backend/system
_COMMON_DIR = _APP_DIR.parent / "common"              # backend/common
# Insert common first, the app dir second — each insert(0) puts the
# app dir at the very front so app-local packages (e.g. system's
# ``models``) shadow same-named shared packages.
for _entry in (str(_COMMON_DIR), str(_APP_DIR)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)


@pytest.fixture()
def tmp_data_root(tmp_path: Path) -> Path:
    """Per-test data root for ``SettingsStore``."""
    return tmp_path


@pytest.fixture()
def clean_env(monkeypatch):
    """Strip ``MODULES_ENABLED`` so tests get the default behaviour."""
    monkeypatch.delenv("MODULES_ENABLED", raising=False)
