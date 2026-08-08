"""Default storage configuration for the macros module."""

from pathlib import Path

# Resolve the repository root rather than relying on the process working
# directory.  This keeps the documented ``./macros/`` location stable when
# the backend is launched from another directory (for example by uvicorn).
PROJECT_ROOT = Path(__file__).resolve().parents[3]
MACROS_STORAGE_DIR = PROJECT_ROOT / "macros"

__all__ = ["PROJECT_ROOT", "MACROS_STORAGE_DIR"]
