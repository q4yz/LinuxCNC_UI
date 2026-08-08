"""Pluggable compiler package for the :mod:`machineconfig` module.

Importing this package triggers :func:`base.autoload`, which walks the
sibling modules and registers every concrete :class:`Compiler`
subclass against :data:`base.registry`. The router consumes that
registry to populate the frontend compiler selector.
"""

from __future__ import annotations

from .base import (
    DEFAULT_SOURCE_MARKER,
    Compiler,
    CompilerRegistry,
    autoload,
    register_compiler,
    registry,
)
from .heater_extractor import (
    HardwareHeater,
    HeaterExtractor,
    derive_heater_name,
)
from .klipper_linuxcnc import KlipperToLinuxCNCCompiler

# Side-effect import: ensure the registry is populated the moment a
# caller does ``from backend.modules.machineconfig import compilers``.
autoload()

__all__ = [
    "Compiler",
    "CompilerRegistry",
    "DEFAULT_SOURCE_MARKER",
    "HardwareHeater",
    "HeaterExtractor",
    "KlipperToLinuxCNCCompiler",
    "autoload",
    "derive_heater_name",
    "register_compiler",
    "registry",
]