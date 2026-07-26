"""Pluggable compiler base class for the machineconfig module.

Issue #41 introduces an object-oriented compiler framework so the
``Klipper → LinuxCNC`` translation (and any future compilers) can be
selected and chained through one uniform interface.

The base :class:`Compiler` is intentionally minimal: subclasses
declare a stable ``id`` / ``title`` pair, an optional ``source_marker``
substring (default :data:`DEFAULT_SOURCE_MARKER`), and override
:meth:`Compiler.compile` to do the actual translation.

A lightweight registry (``compilers.registry``) collects every concrete
implementation discovered under :mod:`backend.modules.machineconfig.compilers`.
Adding a new compiler is a one-file change: drop a new subclass in this
package, optionally re-export it from :mod:`compilers.__init__`, and it
becomes visible to the frontend selector on the next request.

The framework deliberately avoids two things:

* **Path-traversal hardening.** The scope of #41 explicitly puts this
  out of scope — see the issue body. File handling stays direct.
* **Sandboxing / exec security.** Compilers run in-process on the
  backend. A future hardening round can wrap them in a worker if
  untrusted profiles become a real risk.
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterable, List

logger = logging.getLogger("backend.modules.machineconfig.compilers")


#: Substring every recognised compiler looks for inside a source file
#: to flag it as "compileable" via the inline action button. The marker
#: is intentionally a comment token so Klipper / Marlin / RepRap style
#: configs treat it as a no-op rather than a syntax error.
DEFAULT_SOURCE_MARKER = "#Start"


class Compiler(ABC):
    """Abstract base class for every machine-config compiler.

    Subclasses MUST override :meth:`compile` and SHOULD override
    :attr:`id`, :attr:`title`, and (optionally) :attr:`source_marker`.
    The :meth:`supports` and :meth:`has_source_marker` helpers
    encapsulate the marker detection the frontend relies on to surface
    the inline "Compile" action next to a profile file.
    """

    #: Stable identifier used by the API and the registry. Lower-case,
    #: kebab/snake. MUST be unique app-wide.
    id: str = "base"

    #: Human-readable title shown in the frontend compiler dropdown.
    title: str = "Base Compiler"

    #: Substring that flags a source file as eligible for this compiler.
    #: When ``None`` the file is always eligible (e.g. a future raw
    #: translator that doesn't care about markers).
    source_marker: str | None = DEFAULT_SOURCE_MARKER

    # ------------------------------------------------------------------ #
    # Public surface                                                     #
    # ------------------------------------------------------------------ #

    @abstractmethod
    def compile(self, source_path: Path, output_dir: Path) -> List[Path]:
        """Translate ``source_path`` and write outputs into ``output_dir``.

        Implementations are expected to:

        * clear or pre-populate ``output_dir`` as needed (the registry
          already wipes it before calling ``compile``),
        * copy the original source alongside the generated artifacts so
          the deploy step always has a complete staged payload,
        * return the list of files written (relative to ``output_dir``)
          so the API surface can report them to the operator.

        Args:
            source_path: Absolute path to the source ``.cfg`` file.
            output_dir: Pre-existing, empty directory ready to receive
                generated artifacts.

        Returns:
            The list of artifact paths actually written under
            ``output_dir`` (typically the union of ``output_dir /
            "machine.cfg"`` plus the INI/HAL/JSON siblings).

        Raises:
            FileNotFoundError: ``source_path`` does not exist.
            ValueError: Source failed a sanity check the compiler cares
                about (e.g. malformed INI, missing required sections).
        """

    # ------------------------------------------------------------------ #
    # Convenience helpers                                                #
    # ------------------------------------------------------------------ #

    def supports(self, source_path: Path) -> bool:
        """Return ``True`` if ``source_path`` is a candidate for this compiler.

        The default implementation only checks the file extension; the
        marker detection lives in :meth:`has_source_marker` so callers
        can decide independently whether to *show* the inline compile
        button vs. *actually* compile a given profile.
        """
        return source_path.is_file() and source_path.suffix.lower() == ".cfg"

    def has_source_marker(self, source_path: Path, *, max_bytes: int = 8192) -> bool:
        """Return ``True`` when ``source_path`` contains the marker.

        The check reads only the first ``max_bytes`` of the file so a
        multi-megabyte config does not pay a full scan. The marker is
        matched as a substring of those leading bytes; line-start
        variants (e.g. ``"#Start printer.cfg"``) match too because the
        match is plain ``in``.
        """
        marker = self.source_marker
        if not marker:
            # Compiler opted out of marker detection — every supported
            # file is considered "marked".
            return self.supports(source_path)

        if not self.supports(source_path):
            return False

        try:
            with open(source_path, "r", encoding="utf-8", errors="replace") as handle:
                head = handle.read(max_bytes)
        except OSError as exc:
            logger.warning("Cannot read %s for marker check: %s", source_path, exc)
            return False
        return marker in head


# ---------------------------------------------------------------------- #
# Compiler registry                                                     #
# ---------------------------------------------------------------------- #


class CompilerRegistry:
    """In-process registry of :class:`Compiler` implementations.

    Registrations happen at import time — :func:`register_compiler`
    is the only mutator and is idempotent on ``id`` collisions (the
    later registration wins and the earlier one is logged at WARNING
    so a typo never silently shadows a working compiler).
    """

    def __init__(self) -> None:
        self._compilers: dict[str, Compiler] = {}

    def register(self, compiler: Compiler) -> None:
        """Register ``compiler`` under :attr:`Compiler.id`.

        A collision (same id) logs a warning and replaces the previous
        instance. We deliberately replace rather than reject so the
        unit tests can override behaviour without re-importing the
        module.
        """
        if not isinstance(compiler, Compiler):
            raise TypeError(
                f"registry.register() expects a Compiler, got {type(compiler).__name__}"
            )
        existing = self._compilers.get(compiler.id)
        if existing is not None and existing is not compiler:
            logger.warning(
                "Compiler id '%s' is already registered (%s); replacing with %s",
                compiler.id,
                type(existing).__name__,
                type(compiler).__name__,
            )
        self._compilers[compiler.id] = compiler

    def get(self, compiler_id: str) -> Compiler:
        """Return the compiler registered under ``compiler_id``.

        Raises:
            KeyError: No compiler is registered under the supplied id.
        """
        try:
            return self._compilers[compiler_id]
        except KeyError as exc:
            raise KeyError(
                f"Unknown compiler id '{compiler_id}'. "
                f"Known: {sorted(self._compilers)}"
            ) from exc

    def all(self) -> List[Compiler]:
        """Return every registered compiler, ordered by ``id``."""
        return [self._compilers[key] for key in sorted(self._compilers)]

    def ids(self) -> List[str]:
        """Return the registered compiler ids in sorted order."""
        return sorted(self._compilers)

    def __contains__(self, compiler_id: object) -> bool:
        return isinstance(compiler_id, str) and compiler_id in self._compilers

    def __len__(self) -> int:
        return len(self._compilers)


# Module-level singleton shared by the router and the unit tests. New
# compilers register themselves against this instance from their
# ``__init__.py`` so the registry stays in sync with the package layout.
registry = CompilerRegistry()


def register_compiler(compiler: Compiler) -> Compiler:
    """Register ``compiler`` against :data:`registry` and return it.

    Imported and called from each concrete compiler's module so the
    side effect happens at import time, which mirrors the historical
    pattern in :mod:`backend.services.hal_compiler`.
    """
    registry.register(compiler)
    return compiler


def iter_compiler_classes() -> Iterable[type[Compiler]]:
    """Yield every concrete :class:`Compiler` subclass declared in this package.

    The discovery walks :mod:`backend.modules.machineconfig.compilers`,
    imports every sibling module, and returns the classes that look
    like a Compiler (excluding the base class itself). The function
    never raises — a broken module is logged and skipped so a single
    typo cannot break the whole registry.
    """

    import importlib
    import pkgutil

    # ``base`` is the module that defines this function, so its
    # ``__path__`` attribute is ``None`` — the package attribute
    # lives on the package ``__init__`` module. Import it directly
    # so we always have the package ``__path__`` to walk.
    package_name = __name__.rsplit(".", 1)[0]
    package = importlib.import_module(package_name)
    pkg_path = getattr(package, "__path__", None)
    if pkg_path is None:
        return []

    found: list[type[Compiler]] = []
    for _, module_name, _ in pkgutil.iter_modules(pkg_path):
        if module_name in {"base", "__init__"}:
            continue
        full = f"{package_name}.{module_name}"
        try:
            module = importlib.import_module(full)
        except Exception as exc:  # noqa: BLE001 - intentional broad catch
            logger.error("Failed to import compiler module %s: %s", full, exc)
            continue
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, Compiler)
                and attr is not Compiler
            ):
                found.append(attr)
    return found


def autoload() -> None:
    """Discover and register every concrete :class:`Compiler` in the package.

    Called once from the module's package ``__init__`` so the registry
    is populated by the time the FastAPI router is built. The function
    is idempotent — repeated calls re-register the same instances but
    the registry's collision check short-circuits noise.
    """
    for cls in iter_compiler_classes():
        try:
            instance = cls()
        except Exception as exc:  # noqa: BLE001 - intentional broad catch
            logger.error("Cannot instantiate %s: %s", cls.__name__, exc)
            continue
        register_compiler(instance)


__all__ = [
    "Compiler",
    "CompilerRegistry",
    "DEFAULT_SOURCE_MARKER",
    "autoload",
    "register_compiler",
    "registry",
]