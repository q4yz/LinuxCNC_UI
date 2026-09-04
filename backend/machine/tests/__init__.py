"""Pytest package marker: keep the machine-backend tests importable.

The machine tests import the shared test factory as
``from tests._module_app_factory import build_module_app`` — the
``tests`` package resolves because the app directory
(``backend/machine/``) is pushed onto ``sys.path`` by
``conftest.py``.
"""
