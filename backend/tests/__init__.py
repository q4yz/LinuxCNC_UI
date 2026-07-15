"""Pytest config: ensure the backend package is importable.

These tests live alongside the source tree (``backend/tests/``), so we
need to push ``backend/`` onto ``sys.path`` before any ``from core...``
imports work. We also gate the whole module behind a probe so the
existing ``python -m compileall backend`` flow stays unaffected.
"""

import os
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# Tests that build the ModuleRegistry need an explicit data root so
# they don't pollute the working directory.
os.environ.setdefault("DATA_ROOT", str(_BACKEND_DIR / "tests" / ".tmp"))