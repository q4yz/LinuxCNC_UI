"""Filesystem-backed storage for ``.macro`` files.

MacroStorage is the canonical persistence layer for custom macros
(issue #92). It owns every read / write / list / delete operation
against the macros directory; the HTTP router in
:mod:`backend.modules.macros.router` is a thin wrapper that hands
callers a JSON-friendly view of the same surface.

Key properties:

* **Strict ``.macro`` extension.** Every file in the storage root
  that does not end with ``.macro`` is ignored — the directory is
  shared with the rest of the repo so we never want to confuse an
  operator's stray file with a managed macro.

* **Atomic write.** :meth:`write` persists to a sibling temp file
  first and then atomically renames it with :func:`os.replace`. A
  crash mid-write either leaves the previous macro intact or the
  new one in place — never a half-written file. The pattern mirrors
  :meth:`core.settings_store.SettingsStore._atomic_write`.

* **Defensive name validation.** Names must match
  ``^[A-Za-z0-9._-]{1,64}$``; ``..`` is rejected outright. The
  security waiver for this iteration explicitly says path-traversal
  protection and sandboxing are out of scope, but we still reject
  obvious traversal sequences so a future ticket can lift the
  waiver without rewriting this layer.

The class is intentionally framework-agnostic: it does not import
FastAPI or Pydantic. Validation is the module's job; storage's job
is to make the bytes durable.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------- #
# Constants                                                               #
# ---------------------------------------------------------------------- #


#: File extension every macro file must end with (case-sensitive).
EXTENSION = ".macro"

#: Allowed character set for macro names. ``/`` and the path
#: separator are deliberately excluded so the regex alone blocks the
#: most obvious traversal attempts.
_NAME_REGEX = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


# ---------------------------------------------------------------------- #
# Errors                                                                  #
# ---------------------------------------------------------------------- #


class InvalidMacroNameError(ValueError):
    """Raised when a caller hands :class:`MacroStorage` a name that
    fails the validation rules (regex, length, or ``..`` segment).
    """


class MacroNotFoundError(FileNotFoundError):
    """Raised when an operation targets a macro that does not exist.

    Subclassing :class:`FileNotFoundError` (rather than introducing a
    new error hierarchy) keeps callers that already handle
    ``FileNotFoundError`` working without a code change.
    """


# ---------------------------------------------------------------------- #
# Helpers                                                                 #
# ---------------------------------------------------------------------- #


def default_storage_root() -> Path:
    """Return the default macros directory at ``<repo>/macros/``.

    The repo root is computed from this file's location — three
    parents up from :file:`backend/modules/macros/storage.py` puts
    us at the repo root, which matches the convention used by the
    rest of the backend (``machine_config/`` and ``nc_files/`` are
    resolved the same way).

    Tests can monkeypatch this function via
    ``monkeypatch.setattr(macros.storage, "default_storage_root", ...)``
    to redirect the default root to a ``tmp_path`` tree.
    """
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "macros"


# ---------------------------------------------------------------------- #
# Storage                                                                 #
# ---------------------------------------------------------------------- #


class MacroStorage:
    """Filesystem-backed CRUD over a directory of ``.macro`` files.

    Args:
        root_dir: Directory that holds the ``.macro`` files. Created
            on first write if it does not exist; reads against a
            missing directory return empty results (never raise).
    """

    def __init__(self, root_dir: Path) -> None:
        if root_dir is None:
            raise ValueError("root_dir must not be None")
        self._root = Path(root_dir)

    # ------------------------------------------------------------------ #
    # Properties                                                          #
    # ------------------------------------------------------------------ #

    @property
    def root(self) -> Path:
        """Absolute path of the directory this storage writes to."""
        return self._root

    # ------------------------------------------------------------------ #
    # Validation                                                          #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _validate(name: str) -> str:
        """Return ``name`` unchanged when it passes validation.

        Raises:
            InvalidMacroNameError: If the name is not a string, does
                not match :data:`_NAME_REGEX`, or is ``..`` / ``.``.
        """
        if not isinstance(name, str):
            raise InvalidMacroNameError(
                f"macro name must be a string, got {type(name).__name__}"
            )
        # ``/`` and ``\\`` are already excluded by the regex's character
        # class; ``..`` is not, so we defensively reject it. We also
        # reject the single-dot name for symmetry.
        if name in {"", ".", ".."}:
            raise InvalidMacroNameError(
                f"invalid macro name: {name!r}"
            )
        if not _NAME_REGEX.match(name):
            raise InvalidMacroNameError(
                f"invalid macro name: {name!r} "
                "(must match ^[A-Za-z0-9._-]{1,64}$)"
            )
        return name

    # ------------------------------------------------------------------ #
    # CRUD                                                                #
    # ------------------------------------------------------------------ #

    def list(self) -> List[str]:
        """Return macro names (without ``.macro``) sorted alphabetically.

        A missing or empty directory returns an empty list. Files
        that do not end with ``.macro`` are ignored.
        """
        if not self._root.exists():
            return []

        names: List[str] = []
        for entry in self._root.iterdir():
            if not entry.is_file():
                continue
            if not entry.name.endswith(EXTENSION):
                continue
            names.append(entry.name[: -len(EXTENSION)])
        names.sort()
        return names

    def read(self, name: str) -> str:
        """Return the raw text content of the macro.

        Raises:
            InvalidMacroNameError: If ``name`` fails validation.
            MacroNotFoundError: If no ``<name>.macro`` file exists.
        """
        valid = self._validate(name)
        path = self._root / f"{valid}{EXTENSION}"
        if not path.exists():
            raise MacroNotFoundError(
                f"macro not found: {valid}{EXTENSION}"
            )
        return path.read_text(encoding="utf-8")

    def exists(self, name: str) -> bool:
        """Return ``True`` iff a macro named ``name`` exists.

        Invalid names return ``False`` (rather than raising) so the
        router can use ``exists`` as a cheap pre-flight check before
        issuing a delete.
        """
        try:
            valid = self._validate(name)
        except InvalidMacroNameError:
            return False
        path = self._root / f"{valid}{EXTENSION}"
        return path.exists()

    def write(self, name: str, content: str) -> int:
        """Persist ``content`` to ``<name>.macro`` atomically.

        Args:
            name: Validated macro name (without extension).
            content: Raw text payload. Decoded as UTF-8 on read.

        Returns:
            The byte size of the persisted payload (matches the
            ``size`` field in the router response).

        Raises:
            InvalidMacroNameError: If ``name`` fails validation.
        """
        if not isinstance(content, str):
            raise TypeError(
                f"macro content must be str, got {type(content).__name__}"
            )

        valid = self._validate(name)
        self._root.mkdir(parents=True, exist_ok=True)
        path = self._root / f"{valid}{EXTENSION}"

        # ``delete=False`` so we can rename onto the final path
        # cross-platform; ``dir=`` pins the temp file to the same
        # filesystem as the target so ``os.replace`` stays atomic.
        fd, tmp_path = tempfile.mkstemp(
            prefix=f".{valid}-",
            suffix=f"{EXTENSION}.tmp",
            dir=str(self._root),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fp:
                fp.write(content)
                fp.flush()
                os.fsync(fp.fileno())
            os.replace(tmp_path, path)
        except Exception:
            # Best-effort cleanup of the temp file on failure; never
            # raise from cleanup so the original error propagates.
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        return path.stat().st_size

    def delete(self, name: str) -> None:
        """Remove ``<name>.macro`` from disk.

        Raises:
            InvalidMacroNameError: If ``name`` fails validation.
            MacroNotFoundError: If no ``<name>.macro`` file exists.
        """
        valid = self._validate(name)
        path = self._root / f"{valid}{EXTENSION}"
        if not path.exists():
            raise MacroNotFoundError(
                f"macro not found: {valid}{EXTENSION}"
            )
        path.unlink()


__all__ = [
    "MacroStorage",
    "EXTENSION",
    "InvalidMacroNameError",
    "MacroNotFoundError",
    "default_storage_root",
]
