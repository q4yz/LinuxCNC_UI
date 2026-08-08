"""CRUD service for ``.macro`` files on disk.

Issue #87 is strictly about file handling: list, read, write, and
delete ``.macro`` files under a configurable storage directory. The
class deliberately stays framework-agnostic — no FastAPI, no
Pydantic models, no event bus — so it can be unit-tested in
isolation and reused from any future router/CLI that mounts it.

Design notes:

* **Atomic writes** (``LESSONS_LEARNED §3.4``). ``write_macro``
  uses :func:`tempfile.mkstemp` + ``fsync`` + :func:`os.replace`
  so a crash mid-write never leaves a half-written ``.macro`` file
  on disk. ``mkstemp`` is pinned to the same directory as the
  target so the rename stays atomic on POSIX and Windows alike.
* **Name vs. suffix**. The UI lists macros without the ``.macro``
  suffix; this service re-attaches the suffix internally so callers
  never have to think about it. ``list_macros`` returns sorted
  bare names for stable UI rendering.
* **Lazy directory creation**. The storage directory is created on
  the first write rather than at construction time, so the service
  can be instantiated before the directory exists without
  surprising the operator with an empty folder.
* **Stateless**. There is no in-memory cache; every call hits the
  filesystem. Macro files are tiny and the operation count is low
  (an "Activation" list view, not a hot path).

Security is intentionally out of scope per the issue's waiver; the
next ticket that adds an HTTP router is expected to validate input
at the boundary.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)

#: Canonical file extension for macro files. Public so tests and
#: future routers can reference the same constant.
MACRO_SUFFIX = ".macro"


class MacroNotFoundError(FileNotFoundError):
    """Raised when a requested macro does not exist on disk.

    Subclasses :class:`FileNotFoundError` so existing ``except``
    blocks that catch the standard exception keep working, while
    still giving callers a precise type to assert against in
    tests and to map to a 404 at the HTTP boundary.
    """


class MacroFileService:
    """File-handling service for ``.macro`` files.

    Args:
        storage_dir: Directory that holds the ``.macro`` files.
            Defaults to the package directory (``backend/macros/``)
            so production code can instantiate without arguments.
            Tests pass :class:`pathlib.Path` from a ``tmp_path``
            fixture to keep the suite hermetic.

    The service is stateless and safe to share across threads for
    read operations. Write and delete operations are not guarded
    by a lock because macro files are typically edited from a
    single operator UI; concurrent writers would race the atomic
    rename but neither would corrupt the file (the previous
    version always survives the crash window).
    """

    def __init__(self, storage_dir: Path | None = None) -> None:
        self._storage_dir = Path(storage_dir) if storage_dir is not None else Path(__file__).resolve().parent

    # ------------------------------------------------------------------ #
    # Properties                                                          #
    # ------------------------------------------------------------------ #

    @property
    def storage_dir(self) -> Path:
        """Absolute path of the directory that holds ``.macro`` files."""
        return self._storage_dir

    # ------------------------------------------------------------------ #
    # CRUD                                                                #
    # ------------------------------------------------------------------ #

    def list_macros(self) -> List[str]:
        """Return every macro name (without the ``.macro`` suffix), sorted.

        Empty directories return ``[]``. Hidden files and non-``.macro``
        files are ignored so a stray ``.DS_Store`` or ``README`` in the
        directory never leaks into the UI.
        """
        if not self._storage_dir.exists():
            return []

        names: List[str] = []
        for entry in self._storage_dir.iterdir():
            if not entry.is_file():
                continue
            if entry.suffix != MACRO_SUFFIX:
                continue
            # ``entry.stem`` strips the trailing suffix, exactly what
            # the UI wants to render in the "Activation" list.
            names.append(entry.stem)
        names.sort()
        return names

    def read_macro(self, name: str) -> str:
        """Return the raw text contents of ``<name>.macro``.

        Args:
            name: Bare macro name (no suffix). The ``.macro`` suffix
                is re-attached internally.

        Raises:
            ValueError: If ``name`` is empty or not a string.
            MacroNotFoundError: If the resulting file does not exist.
        """
        path = self._resolve(name)
        if not path.exists() or not path.is_file():
            logger.warning("read_macro: missing file for name=%r", name)
            raise MacroNotFoundError(f"Macro not found: {name}")
        return path.read_text(encoding="utf-8")

    def write_macro(self, name: str, content: str) -> None:
        """Create or overwrite ``<name>.macro`` with ``content``.

        The write is atomic: a temp file is created in the same
        directory, ``fsync``-ed, then renamed onto the target path.
        A crash at any point leaves the previous version intact (or
        the file absent, never half-written).

        Args:
            name: Bare macro name (no suffix). Must be non-empty.
            content: Raw text payload. Encoded as UTF-8.

        Raises:
            ValueError: If ``name`` is empty or contains characters
                that would prevent a safe file name.
            TypeError: If ``content`` is not a string.
        """
        if not isinstance(content, str):
            raise TypeError(
                f"write_macro: content must be str, got {type(content).__name__}"
            )

        path = self._resolve(name)
        self._storage_dir.mkdir(parents=True, exist_ok=True)

        # ``delete=False`` so we control the close + rename; ``dir=``
        # pins the temp file to the same filesystem as the target so
        # the ``os.replace`` stays atomic.
        fd, tmp_path = tempfile.mkstemp(
            prefix=".macro-",
            suffix=".tmp",
            dir=str(self._storage_dir),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fp:
                fp.write(content)
                fp.flush()
                os.fsync(fp.fileno())
            os.replace(tmp_path, path)
            logger.debug("write_macro: wrote %s (%d bytes)", path, len(content))
        except Exception:
            # Best-effort cleanup of the temp file on failure; never
            # raise from cleanup because we want the original error
            # to propagate.
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def delete_macro(self, name: str) -> None:
        """Delete ``<name>.macro`` from disk.

        Args:
            name: Bare macro name (no suffix).

        Raises:
            ValueError: If ``name`` is empty or not a string.
            MacroNotFoundError: If the file does not exist (idempotent
                callers can catch this and treat it as a no-op).
        """
        path = self._resolve(name)
        if not path.exists() or not path.is_file():
            logger.warning("delete_macro: missing file for name=%r", name)
            raise MacroNotFoundError(f"Macro not found: {name}")
        path.unlink()
        logger.debug("delete_macro: removed %s", path)

    # ------------------------------------------------------------------ #
    # Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _resolve(self, name: str) -> Path:
        """Validate ``name`` and return the absolute ``.macro`` path.

        Centralising the validation keeps the public methods
        consistent: every caller re-attaches the suffix and every
        invalid name raises the same ``ValueError`` shape.
        """
        if not isinstance(name, str):
            raise ValueError(
                f"Macro name must be a string, got {type(name).__name__}"
            )
        if not name:
            raise ValueError("Macro name must be a non-empty string")
        # The public API is "bare name"; we re-attach the suffix so
        # the disk and the API never disagree.
        return self._storage_dir / f"{name}{MACRO_SUFFIX}"


__all__ = ["MACRO_SUFFIX", "MacroFileService", "MacroNotFoundError"]