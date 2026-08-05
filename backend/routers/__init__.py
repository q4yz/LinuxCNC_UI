"""HTTP routers exposed by the LinuxCNC UI backend.

Each module under :mod:`backend.routers` is a thin FastAPI
``APIRouter`` that delegates its actual work to the
``backend.services`` package. Mounting happens in
``backend/main.py`` via ``app.include_router(...)``; this package
exists so the ``from routers import ...`` imports in ``main.py``
remain valid regardless of the implicit-namespace-package rules
in the surrounding Python environment.
"""
from .files import router as files
from .macros import router as macros
from .system import router as system
from .websocket import router as websocket

__all__ = ["files", "macros", "system", "websocket"]
