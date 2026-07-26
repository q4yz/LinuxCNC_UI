"""Machineconfig module package.

Issue #41 introduces the new Machine Configuration, Compilation, and
Deployment system. The package hosts the module-scoped HTTP surface
(``/api/v1/modules/machineconfig``), the pluggable compiler
framework, and the settings model — see :mod:`module` for the public
contract.
"""

from .module import setup

__all__ = ["setup"]