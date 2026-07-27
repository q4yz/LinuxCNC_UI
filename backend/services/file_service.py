"""Base :class:`FileService` for the layered filesystem architecture.

Issue #49 funnels every router-level filesystem call through a small
family of service objects so the routers can stay thin HTTP wrappers.
The base class is the generic, reusable primitive; the domain
subclasses (:class:`ConfigFileService`, :class:`ProgramFileService`,
:class:`StagedFileService`, :class:`ActiveFileService`) live in
sibling modules and add the small bits of policy (read-only mode,
profile filtering, G-code extensions) that each root needs.

Scope (mirrors the original ``backend/modules/machineconfig/filesystem.py``
helpers that this class replaces):

* ``list_files(subpath="")`` — flat listing with size, mtime, and a
  ``read_only`` boolean driven by the POSIX mode bit.
* ``read_file(filepath)`` — return raw text content.
* ``write_file(filepath, content, overwrite=True)`` — create or
  overwrite. Honors the ``read_only`` flag for the staged/active
  roots by raising :class:`PermissionError` rather than silently
  flipping the bit.
* ``create_directory(dirpath)`` — recursive ``mkdir``.
* ``delete(path)`` — unlink files and empty folders.
* ``set_read_only(filepath, read_only=True)`` — flip the write bits
  via :func:`os.chmod`. Used by the compile step to snapshot the
  staged payload and by tests that want to flip a single file.

Path safety stays minimal (the ``safe_join`` invariant from
``filesystem.py``): a path that escapes the root raises
:class:`ValueError` so the router can surface a ``400`` to the
frontend. A full traversal hardening pass is out of scope for
issue #49 (and explicitly so for issue #41).
"""

from __future__ import annotations

import configparser
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

logger = logging.getLogger("backend.services.file_service")


@dataclass
class FileMetadata:
    """Single entry inside a :meth:`FileService.list_files` listing.

    Mirrors the ``DirectoryEntry`` shape that the legacy
    ``filesystem.list_tree`` helper returned but adds the
    ``read_only`` flag (driven by the POSIX write bits) and an
    explicit ``modified`` ISO-8601 timestamp so the frontend does
    not have to re-stat every file.
    """

    name: str
    path: str
    parent: Optional[str]
    kind: str  # "file" | "folder"
    size_bytes: int = 0
    modified: Optional[str] = None
    read_only: bool = False
    has_marker: bool = False
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        payload = {
            "name": self.name,
            "path": self.path,
            "parent": self.parent,
            "kind": self.kind,
            "size_bytes": self.size_bytes,
            "modified": self.modified,
            "read_only": self.read_only,
            "has_marker": self.has_marker,
        }
        if self.extra:
            payload.update(self.extra)
        return payload


class FileService:
    """Generic, reusable filesystem operations for a single root.

    Subclasses override :attr:`default_read_only` and (optionally)
    :meth:`_is_allowed_member` to gate the policy that distinguishes
    the four domain roots. The HTTP surface never instantiates a
    bare :class:`FileService`; routers get a domain service via
    :func:`get_config_service` / :func:`get_program_service` /
    :func:`get_staged_service` / :func:`get_active_service`.
    """

    #: Default value for ``read_only`` when the root is brand new and
    #: no per-file flag has been computed. Subclasses flip this to
    #: ``True`` for staged / active roots so the frontend renders the
    #: "write-protected" badge even before any compile has run.
    default_read_only: bool = False

    #: Optional filter ``(name) -> bool`` that restricts the
    #: ``list_files`` output. Used by :class:`ConfigFileService`
    #: to only emit ``.cfg`` files at the top level and by
    #: :class:`ProgramFileService` to only emit ``.gcode`` /
    #: ``.ngc`` files.
    filename_filter: Optional[Callable[[str], bool]] = None

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        # Make sure the root exists; ``mkdir(exist_ok=True)`` is a
        # no-op when the directory is already there so it's safe to
        # call on every request without a separate "bootstrap" step.
        self.root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    # Path safety                                                         #
    # ------------------------------------------------------------------ #

    def safe_join(self, *parts: str) -> Path:
        """Join ``parts`` onto the root and assert the result stays under it.

        Mirrors ``backend.modules.machineconfig.filesystem.safe_join``
        so the contract is byte-for-byte identical for the existing
        call sites. The router still gets a :class:`ValueError` it
        can translate into HTTP 400.
        """
        candidate = self.root.joinpath(*parts).resolve()
        root_resolved = self.root.resolve()
        try:
            candidate.relative_to(root_resolved)
        except ValueError as exc:
            raise ValueError(
                f"Path {candidate} escapes the allowed root {root_resolved}"
            ) from exc
        return candidate

    # ------------------------------------------------------------------ #
    # Listing                                                             #
    # ------------------------------------------------------------------ #

    def list_files(self, subpath: str = "") -> List[FileMetadata]:
        """Return a flat list of every file/folder under ``subpath``.

        The walk is deterministic (sorted by lower-cased path) so the
        frontend gets stable ordering across requests. Folders
        report ``size_bytes=0`` and inherit ``read_only`` from
        the POSIX mode bits the same way files do.
        """
        base = self._resolve_listing_root(subpath)
        if not base.exists():
            return []

        entries: List[FileMetadata] = []
        for path in sorted(base.rglob("*"), key=lambda p: str(p).lower()):
            if self._is_excluded(path):
                continue

            rel = path.relative_to(self.root)
            parent_rel = str(rel.parent) if str(rel.parent) != "." else None
            kind = "folder" if path.is_dir() else "file"

            if kind == "file" and self.filename_filter is not None:
                if not self.filename_filter(path.name):
                    continue

            stat_result = path.stat() if path.exists() else None
            size_bytes = stat_result.st_size if (stat_result and path.is_file()) else 0
            modified = (
                datetime.fromtimestamp(stat_result.st_mtime).isoformat()
                if stat_result
                else None
            )
            read_only = (
                self._stat_read_only(stat_result) if stat_result else self.default_read_only
            )

            entries.append(
                FileMetadata(
                    name=path.name,
                    path=str(rel).replace(os.sep, "/"),
                    parent=parent_rel.replace(os.sep, "/") if parent_rel else None,
                    kind=kind,
                    size_bytes=size_bytes,
                    modified=modified,
                    read_only=read_only,
                )
            )
        return entries

    def _resolve_listing_root(self, subpath: str) -> Path:
        if not subpath:
            return self.root
        return self.safe_join(subpath)

    def _is_excluded(self, path: Path) -> bool:
        """Hook for subclasses to drop hidden / build artefacts."""
        return False

    @staticmethod
    def _stat_read_only(stat_result) -> bool:
        """``True`` when no write bits are set for owner/group/other."""
        if stat_result is None:
            return False
        return (stat_result.st_mode & 0o222) == 0

    # ------------------------------------------------------------------ #
    # Read / write                                                        #
    # ------------------------------------------------------------------ #

    def read_file(self, filepath: str) -> str:
        """Return the text content of ``filepath`` (relative to the root)."""
        target = self.safe_join(filepath)
        if not target.exists() or not target.is_file():
            raise FileNotFoundError(f"File not found: {filepath}")
        return target.read_text(encoding="utf-8", errors="replace")

    def file_exists(self, filepath: str) -> bool:
        """Return ``True`` when ``filepath`` resolves to an existing file."""
        try:
            target = self.safe_join(filepath)
        except ValueError:
            return False
        return target.exists() and target.is_file()

    def write_file(self, filepath: str, content: str, overwrite: bool = True) -> None:
        """Create or overwrite ``filepath`` with ``content``.

        ``read_only`` roots (staged / active) raise
        :class:`PermissionError`; the router translates that into
        a 403. ``overwrite=False`` raises :class:`FileExistsError`
        when the target already exists.
        """
        target = self.safe_join(filepath)

        if target.exists() and not overwrite:
            raise FileExistsError(f"File already exists: {filepath}")

        if target.exists() and not target.is_file():
            raise ValueError(f"Not a file: {filepath}")

        if target.exists() and self._is_path_read_only(target):
            raise PermissionError(
                f"Refusing to overwrite read-only file: {filepath}"
            )

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def write_bytes(self, filepath: str, data: bytes, overwrite: bool = True) -> None:
        """Binary sibling of :meth:`write_file` used by file uploads."""
        target = self.safe_join(filepath)
        if target.exists() and not overwrite:
            raise FileExistsError(f"File already exists: {filepath}")
        if target.exists() and self._is_path_read_only(target):
            raise PermissionError(
                f"Refusing to overwrite read-only file: {filepath}"
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def _is_path_read_only(self, path: Path) -> bool:
        try:
            stat_result = path.stat()
        except OSError:
            return self.default_read_only
        return self._stat_read_only(stat_result)

    # ------------------------------------------------------------------ #
    # Directories                                                         #
    # ------------------------------------------------------------------ #

    def create_directory(self, dirpath: str) -> None:
        """Create ``dirpath`` (and any missing parents) under the root."""
        target = self.safe_join(dirpath)
        if target.exists():
            raise FileExistsError(f"Already exists: {dirpath}")
        target.mkdir(parents=True, exist_ok=False)

    def delete(self, path: str) -> None:
        """Delete a file or empty folder under the root.

        A populated folder raises :class:`IsADirectoryError`; the
        router surfaces that as 400. Recursive folder deletion is
        out of scope for this pass — the legacy behaviour matched
        the same constraint.
        """
        target = self.safe_join(path)
        if not target.exists():
            raise FileNotFoundError(f"Not found: {path}")
        if target.is_dir():
            try:
                target.rmdir()
            except OSError as exc:
                raise IsADirectoryError(
                    f"Folder is not empty; remove contents first: {path}"
                ) from exc
            return
        if self._is_path_read_only(target):
            raise PermissionError(f"Refusing to delete read-only file: {path}")
        target.unlink()

    # ------------------------------------------------------------------ #
    # Read-only toggling                                                  #
    # ------------------------------------------------------------------ #

    def set_read_only(self, filepath: str, read_only: bool = True) -> bool:
        """Flip the POSIX write bits on ``filepath``.

        Returns ``True`` on success, ``False`` when the chmod
        syscall fails (which is non-fatal: a log line is emitted
        and the caller can carry on). Used by the compile step
        to mark every staged artifact as a snapshot.
        """
        try:
            target = self.safe_join(filepath)
        except ValueError as exc:
            logger.debug("set_read_only: unsafe path %s (%s)", filepath, exc)
            return False

        if not target.exists():
            return False

        try:
            current = target.stat().st_mode
            if read_only:
                target.chmod(current & ~0o222)
            else:
                target.chmod(current | 0o222)
            return True
        except OSError as exc:
            logger.debug("chmod failed on %s: %s", target, exc)
            return False

    def mark_tree_read_only(self, directory: Optiona[Path] = None) -> int:
        """Recursively ``chmod`` every entry under ``directory``.

        Defaults to the service root. Returns the number of entries
        that were processed (chmod failures are logged and skipped).
        """
        target = Path(directory) if directory is not None else self.root
        if not target.exists():
            return 0

        count = 0
        for entry in [target, *target.rglob("*")]:
            try:
                current = entry.stat().st_mode
                entry.chmod(current & ~0o222)
                count += 1
            except OSError as exc:
                logger.debug("chmod failed on %s: %s", entry, exc)
        return count

    # ------------------------------------------------------------------ #
    # Tree management                                                     #
    # ------------------------------------------------------------------ #

    def clear_directory(self, directory: Optional[Path] = None) -> None:
        """Recursively empty ``directory`` while keeping the directory itself."""
        import shutil
        import stat

        target = Path(directory) if directory is not None else self.root

        # Windows-specific fix: rmtree fails on read-only files.
        # This callback intercepts the error, flips the write bit, and retries.
        def remove_readonly(func, path, _):
            os.chmod(path, stat.S_IWRITE)
            func(path)

        if target.exists():
            shutil.rmtree(target, onerror=remove_readonly)

        target.mkdir(parents=True, exist_ok=True)

    def copy_tree(self, source: Path, destination: Optional[Path] = None) -> List[str]:
        """Copy every entry under ``source`` into ``destination``.

        ``destination`` defaults to the service root. Returns the
        basenames of the items copied (sorted) so the router can
        report them in the deploy response.
        """
        import shutil

        source_path = Path(source)
        dest_path = Path(destination) if destination is not None else self.root
        dest_path.mkdir(parents=True, exist_ok=True)

        copied: List[str] = []
        for item in source_path.iterdir():
            target = dest_path / item.name
            if item.is_dir():
                shutil.copytree(item, target)
            else:
                shutil.copy2(item, target)
            copied.append(item.name)
        return sorted(copied)

    def rename(self, source: str, destination: str) -> None:
        """Rename ``source`` to ``destination`` under the root.

        Both paths are validated against :meth:`safe_join` so a
        caller cannot escape the root.
        """
        src = self.safe_join(source)
        dst = self.safe_join(destination)
        if not src.exists():
            raise FileNotFoundError(f"Not found: {source}")
        if dst.exists():
            raise FileExistsError(f"Already exists: {destination}")
        if self._is_path_read_only(src):
            raise PermissionError(f"Refusing to rename read-only entry: {source}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)

    # ------------------------------------------------------------------ #
    # INI helpers                                                         #
    # ------------------------------------------------------------------ #

    def parse_machine_name(self) -> Optional[str]:
        """Best-effort detection of the current machine name.

        Reads ``[EMC] MACHINE`` from the first ``.ini`` file in the
        root. Returns ``None`` when the directory is empty or the
        key is missing — the frontend renders a friendly
        placeholder in that case.
        """
        if not self.root.exists():
            return None
        candidates = sorted(self.root.glob("*.ini"))
        if not candidates:
            return None

        parser = configparser.ConfigParser()
        try:
            parser.read(candidates[0], encoding="utf-8")
        except (configparser.Error, OSError):
            return None

        if parser.has_option("EMC", "MACHINE"):
            value = parser.get("EMC", "MACHINE").strip()
            return value or None
        return None


__all__ = [
    "FileMetadata",
    "FileService",
]
