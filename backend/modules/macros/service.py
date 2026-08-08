"""CRUD service for custom ``.macro`` files."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

from .settings import MACROS_STORAGE_DIR

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
    """Store and retrieve ``.macro`` files from a configurable directory.

    The service is stateless and safe to share across threads for
    read operations. Write and delete operations are not guarded
    by a lock because macro files are typically edited from a
    single operator UI; concurrent writers would race the atomic
    rename but neither would corrupt the file (the previous
    version always survives the crash window).

    Design notes:

    * **Atomic writes** (``LESSONS_LEARNED §3.4``). ``write_macro``
      uses :func:`tempfile.mkstemp` + ``fsync`` + :func:`os.replace`
      so a crash mid-write never leaves a half-written ``.macro``
      file on disk. ``mkstemp`` is pinned to the same directory
      as the target so the rename stays atomic on POSIX and
      Windows alike.
    * **Strict ``.macro`` extension**. The UI lists macros
      without the suffix; this service re-attaches the suffix
      internally so callers never have to think about it.
      ``list_macros`` returns sorted bare names for stable UI
      rendering. Inputs that carry a different suffix (``foo.txt``,
      ``foo.py``) are rejected — the on-disk extension must always
      be ``.macro`` exactly.
    * **Lazy directory creation**. The storage directory is
      created on the first write rather than at construction
      time, so the service can be instantiated before the
      directory exists without surprising the operator with an
      empty folder.

    Security is intentionally out of scope per the issue's
    waiver; the next ticket that adds an HTTP router is expected
    to validate input at the boundary.
    """

    def __init__(self, storage_dir: Path | None = None) -> None:
        self._storage_dir = Path(storage_dir or MACROS_STORAGE_DIR)

    @property
    def storage_dir(self) -> Path:
        """Return the configured macro storage directory."""
        return self._storage_dir

    def list_macros(self) -> list[str]:
        """Return sorted macro filenames without the ``.macro`` suffix.

        Empty directories return ``[]``. Hidden files (anything
        whose name starts with ``.``) and non-``.macro`` files
        are ignored so a stray ``.DS_Store`` or ``README`` in
        the directory never leaks into the UI.
        """
        if not self._storage_dir.exists():
            return []

        names: list[str] = []
        for entry in self._storage_dir.iterdir():
            if not entry.is_file():
                continue
            if entry.name.startswith("."):
                # POSIX hidden files (``.macro`` editor backups,
                # ``.DS_Store``, etc.) are not user macros.
                continue
            if entry.suffix != MACRO_SUFFIX:
                continue
            # ``entry.stem`` strips the trailing suffix, exactly
            # what the UI wants to render in the "Activation" list.
            names.append(entry.stem)
        names.sort()
        return names

    def read_macro(self, name: str) -> str:
        """Return the raw contents of a macro, raising if it is missing.

        Args:
            name: Bare macro name (no suffix). The ``.macro``
                suffix is re-attached internally.

        Raises:
            ValueError: If ``name`` is empty, not a string, or
                carries a non-``.macro`` suffix.
            MacroNotFoundError: If the resulting file does not
                exist.
        """
        path = self._path_for(name)
        if not path.exists() or not path.is_file():
            logger.warning("read_macro: missing file for name=%r", name)
            raise MacroNotFoundError(f"Macro not found: {name}")
        return path.read_text(encoding="utf-8")

    def write_macro(self, name: str, content: str) -> None:
        """Atomically create or replace a macro with the raw text payload.

        The write is atomic: a temp file is created in the same
        directory, ``fsync``-ed, then renamed onto the target
        path. A crash at any point leaves the previous version
        intact (or the file absent, never half-written).

        Args:
            name: Bare macro name (no suffix). Must be non-empty
                and must not carry a non-``.macro`` suffix.
            content: Raw text payload. Encoded as UTF-8.

        Raises:
            ValueError: If ``name`` is empty or carries a
                non-``.macro`` suffix.
            TypeError: If ``content`` is not a string.
        """
        if not isinstance(content, str):
            raise TypeError(
                f"write_macro: content must be str, got {type(content).__name__}"
            )

        path = self._path_for(name)
        path.parent.mkdir(parents=True, exist_ok=True)

        # ``delete=False`` so we control the close + rename; ``dir=``
        # pins the temp file to the same filesystem as the target
        # so the ``os.replace`` stays atomic.
        fd, tmp_path = tempfile.mkstemp(
            prefix=".macro-",
            suffix=".tmp",
            dir=str(path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fp:
                fp.write(content)
                fp.flush()
                os.fsync(fp.fileno())
            os.replace(tmp_path, path)
            logger.debug("write_macro: wrote %s (%d bytes)", path, len(content))
        except Exception:
            # Best-effort cleanup of the temp file on failure;
            # never raise from cleanup because we want the
            # original error to propagate.
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def delete_macro(self, name: str) -> None:
        """Delete a macro, raising if it is missing.

        Args:
            name: Bare macro name (no suffix).

        Raises:
            ValueError: If ``name`` is empty, not a string, or
                carries a non-``.macro`` suffix.
            MacroNotFoundError: If the file does not exist
                (idempotent callers can catch this and treat it
                as a no-op).
        """
        path = self._path_for(name)
        if not path.exists() or not path.is_file():
            logger.warning("delete_macro: missing file for name=%r", name)
            raise MacroNotFoundError(f"Macro not found: {name}")
        path.unlink()
        logger.debug("delete_macro: removed %s", path)

    def _path_for(self, name: str) -> Path:
        """Validate ``name`` and return the absolute ``.macro`` path.

        Centralising the validation keeps the public methods
        consistent: every caller re-attaches the suffix and every
        invalid name raises the same ``ValueError`` shape.

        The caller may pass either a bare name (``"foo"``) or one
        already carrying the ``.macro`` suffix (``"foo.macro"``);
        both normalise to the same on-disk path. Any other suffix
        (``"foo.txt"``, ``"foo.py"``) is rejected so the on-disk
        extension stays strictly ``.macro``.

        Security note (per the issue's security waiver): no
        path-traversal validation is performed here. The next
        ticket that wires this service to a router is expected
        to add input validation at the HTTP boundary.
        """
        if not isinstance(name, str):
            raise ValueError(
                f"Macro name must be a string, got {type(name).__name__}"
            )
        if not name:
            raise ValueError("Macro name must be a non-empty string")
        p = Path(name)
        if p.suffix and p.suffix != MACRO_SUFFIX:
            raise ValueError(
                f"Macro name must not include a non-.macro suffix: {name!r}"
            )
        bare = p.stem
        if not bare:
            raise ValueError(
                f"Macro name must have a non-empty stem: {name!r}"
            )
        # The public API is "bare name"; we re-attach the suffix
        # so the disk and the API never disagree.
        return self._storage_dir / f"{bare}{MACRO_SUFFIX}"


__all__ = ["MACRO_SUFFIX", "MacroFileService", "MacroNotFoundError"]
