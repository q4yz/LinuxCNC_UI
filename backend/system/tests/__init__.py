"""Pytest package marker: keep the system-service tests importable.

The system tests import the shared test factory as
``from tests._module_app_factory import build_module_app`` - the
``tests`` package resolves because the app directory
(``backend/system/``) is pushed onto ``sys.path`` by
``conftest.py``.
"""
