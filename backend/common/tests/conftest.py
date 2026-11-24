# Accounts (#131): tests never touch the installation's user database or
# session key — each run gets its own (core.users_db / core.session_token).
import os as _os
import tempfile as _tempfile

_AUTH_DIR = _tempfile.mkdtemp(prefix="linuxcnc-ui-auth-")
_os.environ.setdefault("LINUXCNC_UI_USERS_DB", _os.path.join(_AUTH_DIR, "users.db"))
_os.environ.setdefault("LINUXCNC_UI_SESSION_SECRET", "test-session-secret")

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
