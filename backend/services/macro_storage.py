"""Filesystem layer for the macro subsystem (issue #7).

All macro files live under ``<repo>/macros/`` (configurable via
the ``MACROS_DIR`` environment variable). The default location is
created on first request via :class:`MacroStorage.__init__`.

The class is intentionally narrow: ``list / read / write / delete``.
Validation lives in :mod:`services.macro_parser` so the storage
layer can stay free of business rules.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .macro_parser import validate_macro_name

logger = logging.getLogger("backend.services.macro_storage")


@dataclass
class MacroFile:
    """Single macro entry returned by :meth:`MacroStorage.list`."""

    name: str
    modified: str
    size: int

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "modified": self.modified,
            "size": self.size,
        }


class MacroStorage:
    """Filesystem-backed CRUD for macros.

    The class is safe to instantiate multiple times; the FastAPI
    router keeps a single module-level instance. Atomic writes use
    a ``temp + replace`` dance so a crash mid-save never leaves a
    half-written file behind.
    """

    def __init__(self, root: Optional[Path] = None) -> None:
        if root is None:
            # ``<repo>/macros`` — the backend lives at ``backend/``,
            # so the repo root is two parents up from this module.
            repo_root = Path(__file__).resolve().parents[2]
            root = Path(os.environ.get("MACROS_DIR", repo_root / "macros"))

        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    # Listing                                                              #
    # ------------------------------------------------------------------ #

    def list(self) -> List[MacroFile]:
        """Return every ``.macro`` file under :attr:`root`."""
        entries: List[MacroFile] = []
        if not self.root.exists():
            return entries

        for path in sorted(self.root.glob("*.macro"), key=lambda p: p.name.lower()):
            try:
                stat = path.stat()
            except OSError as exc:
                logger.warning("macro_storage: stat failed for %s: %s", path, exc)
                continue
            entries.append(
                MacroFile(
                    name=path.name,
                    modified=datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    size=stat.st_size,
                )
            )
        return entries

    # ------------------------------------------------------------------ #
    # Read / write / delete                                                #
    # ------------------------------------------------------------------ #

    def read(self, name: str) -> str:
        """Return the UTF-8 text content of ``name``.

        Raises :class:`FileNotFoundError` and :class:`ValueError`
        which the router translates into 404 / 400 responses.
        """
        safe_name = validate_macro_name(name)
        path = self.root / safe_name
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"macro not found: {safe_name}")
        return path.read_text(encoding="utf-8", errors="replace")

    def write(self, name: str, content: str) -> str:
        """Persist ``content`` to ``name``. Returns the canonical name."""
        safe_name = validate_macro_name(name)
        target = self.root / safe_name

        # Atomic write: stage to a sibling temp file then ``replace``.
        # ``os.replace`` is atomic on POSIX when the source and
        # destination are on the same filesystem, which is guaranteed
        # here because both live under :attr:`root`.
        tmp_path = target.with_suffix(target.suffix + ".tmp")
        tmp_path.write_text(content, encoding="utf-8")
        os.replace(tmp_path, target)
        return safe_name

    def delete(self, name: str) -> None:
        """Remove ``name`` from disk. Silent when the file is missing."""
        safe_name = validate_macro_name(name)
        target = self.root / safe_name
        if target.exists():
            try:
                target.unlink()
            except OSError as exc:
                logger.warning("macro_storage: unlink failed for %s: %s", target, exc)
                raise

    def exists(self, name: str) -> bool:
        """Return ``True`` when ``name`` resolves to an existing file."""
        try:
            safe_name = validate_macro_name(name)
        except ValueError:
            return False
        return (self.root / safe_name).exists()


__all__ = ["MacroStorage", "MacroFile"]
