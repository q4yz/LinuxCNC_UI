"""Shared pytest fixtures for the machine-backend tests.

Makes both the app directory (``backend/machine/``) and the shared
library (``backend/common/``) importable, so flat imports like
``from services.X import Y`` and ``from core.settings_store import ...``
resolve inside this suite.
"""
import sys
from pathlib import Path

import pytest

_APP_DIR = Path(__file__).resolve().parents[1]        # backend/machine
_COMMON_DIR = _APP_DIR.parent / "common"              # backend/common
# Make both importable, the app dir at the very front so app-local
# packages shadow same-named shared packages.
#
# The `while ... remove` + unconditional re-insert (instead of the old
# `if not in sys.path` guard) matters since backend/__init__.py exists:
# pytest imports this conftest as ``backend.machine.tests.conftest`` and
# inserts the repo root (the package basedir) into sys.path itself —
# which can leave ``backend/machine`` in the list at a position BELOW
# ``backend/common``. With the guard, machine was skipped and common
# ended up first, so plain ``import tests`` (machine/tests vs
# common/tests vs system/tests all share the bare package name)
# resolved to common's suite — "No module named
# 'tests._module_app_factory'" for every module test.
for _entry in (str(_COMMON_DIR), str(_APP_DIR)):
    while _entry in sys.path:
        sys.path.remove(_entry)
    sys.path.insert(0, _entry)
# If anything imported a foreign ``tests`` package before this conftest
# ran, evict it so the test modules below re-import machine's own.
sys.modules.pop("tests", None)


@pytest.fixture()
def tmp_data_root(tmp_path: Path) -> Path:
    """Per-test data root for ``SettingsStore``."""
    return tmp_path


@pytest.fixture()
def clean_env(monkeypatch):
    """Strip ``MODULES_ENABLED`` so tests get the default behaviour."""
    monkeypatch.delenv("MODULES_ENABLED", raising=False)
