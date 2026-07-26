"""Filesystem helpers for the machineconfig module.

Issue #41 explicitly puts path-traversal prevention and advanced file
execution security *out of scope*. The helpers in this file are direct,
focused wrappers around :mod:`pathlib` operations — they exist to
centralise the three directory roots (``profiles`` / ``ready_for_deploy``
/ ``active``) and to keep the router readable.

Two invariants the helpers enforce:

1. ``profiles_dir`` is **read-write** (the operator can CRUD files
   and folders). ``staged_dir`` and ``active_dir`` are **read-only**
   in spirit; we mark the staged artifacts write-protected after the
   compile step via :func:`mark_staged_readonly` so a misclick on
   the Active dashboard cannot corrupt the staged payload.
2. The router only ever resolves paths through :meth:`resolve` on
   one of the three roots, so a bug in the helper is the only
   place we need to audit if a security review asks about
   traversal hardening later.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Iterable, List, Optional

logger = logging.getLogger("backend.modules.machineconfig.filesystem")


PROJECT_ROOT = Path(__file__).resolve().parents[3]
MACHINE_CONFIG_DIR = PROJECT_ROOT / "machine_config"
PROFILES_DIR = MACHINE_CONFIG_DIR / "profiles"
STAGED_DIR = MACHINE_CONFIG_DIR / "ready_for_deploy"
ACTIVE_DIR = MACHINE_CONFIG_DIR / "active"


def ensure_directories() -> None:
    """Create the three roots if they don't exist yet.

    Safe to call on every boot — :func:`os.makedirs` with
    ``exist_ok=True`` is a no-op when the directory is already there.
    """
    for directory in (PROFILES_DIR, STAGED_DIR, ACTIVE_DIR):
        directory.mkdir(parents=True, exist_ok=True)


class DirectoryEntry:
    """A single node inside a profile / staged / active tree.

    The model is intentionally flat — the frontend builds the tree
    by walking the list and looking up children by ``parent``. A
    full nested structure would couple the API surface to one
    particular rendering approach; a flat list of entries gives the
    frontend the freedom to render either a tree or a flat list.
    """

    def __init__(
        self,
        name: str,
        path: str,
        parent: Optional[str],
        kind: str,
        size_bytes: int = 0,
        has_marker: bool = False,
    ) -> None:
        self.name = name
        self.path = path
        self.parent = parent
        self.kind = kind  # "file" | "folder"
        self.size_bytes = size_bytes
        self.has_marker = has_marker

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "path": self.path,
            "parent": self.parent,
            "kind": self.kind,
            "size_bytes": self.size_bytes,
            "has_marker": self.has_marker,
        }


def safe_join(root: Path, *parts: str) -> Path:
    """Join ``parts`` onto ``root`` and assert the result stays under it.

    The issue brief calls path traversal "out of scope" so this is the
    minimum guardrail: ensure the joined path resolves underneath
    ``root``. A path that escapes (e.g. ``..`` segments) raises
    ``ValueError`` so the router can surface a 400.
    """
    candidate = root.joinpath(*parts).resolve()
    root_resolved = root.resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(
            f"Path {candidate} escapes the allowed root {root_resolved}"
        ) from exc
    return candidate


def list_tree(root: Path, *, has_marker=None) -> List[DirectoryEntry]:
    """Return every file and folder under ``root`` as flat entries.

    Args:
        root: Directory to walk.
        has_marker: Optional callable ``(path) -> bool`` that flags a
            file as carrying the :data:`Compiler.source_marker`. Used
            by the router to inject the inline compile button. When
            ``None``, every file reports ``has_marker=False``.

    The walk is deterministic (sorted by ``str(path)``) so the
    frontend gets stable ordering across requests.
    """
    entries: List[DirectoryEntry] = []
    if not root.exists():
        return entries

    for path in sorted(root.rglob("*"), key=lambda p: str(p).lower()):
        rel = path.relative_to(root)
        parent_rel = str(rel.parent) if str(rel.parent) != "." else None
        kind = "folder" if path.is_dir() else "file"
        marker = False
        if kind == "file" and has_marker is not None:
            try:
                marker = bool(has_marker(path))
            except Exception:  # noqa: BLE001 - intentional broad catch
                marker = False
        entries.append(
            DirectoryEntry(
                name=path.name,
                path=str(rel).replace(os.sep, "/"),
                parent=parent_rel.replace(os.sep, "/") if parent_rel else None,
                kind=kind,
                size_bytes=path.stat().st_size if path.is_file() else 0,
                has_marker=marker,
            )
        )
    return entries


def clear_directory(directory: Path) -> None:
    """Recursively empty ``directory`` while keeping the directory itself.

    Mirrors the helper inside ``backend/services/hal_compiler.py`` so
    the legacy ``HalCompiler`` and the new machineconfig module share
    the same semantics for staging.
    """
    import shutil

    if directory.exists():
        shutil.rmtree(directory)
    directory.mkdir(parents=True, exist_ok=True)


def copy_tree(src: Path, dst: Path) -> List[str]:
    """Copy every entry under ``src`` into ``dst`` and return the names.

    Used by the deploy step to promote staged artifacts into
    ``active_dir``. Returns the basenames of the files copied so the
    router can report them in the response.
    """
    import shutil

    copied: List[str] = []
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = dst / item.name
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)
        copied.append(item.name)
    return sorted(copied)


def mark_staged_readonly(directory: Path) -> int:
    """Remove write permission from every entry under ``directory``.

    The deploy step is the single owner of the staged payload; once
    the operator confirms a deploy, the staged files become a
    snapshot. Making them read-only prevents a console typo from
    silently editing the snapshot and producing a divergent
    ``ready_for_deploy`` / ``active`` pair.
    """
    count = 0
    for entry in [directory, *directory.rglob("*")]:
        try:
            current = entry.stat().st_mode
            entry.chmod(current & ~0o222)
            count += 1
        except OSError as exc:
            # chmod failures are non-fatal — the deploy still works;
            # the read-only flag is a soft guarantee.
            logger.debug("chmod failed on %s: %s", entry, exc)
    return count


def parse_machine_name(active_dir: Path) -> Optional[str]:
    """Best-effort detection of the current machine name.

    The machine name lives in the staged INI's ``[EMC]`` section as
    ``MACHINE = ...``. We look for the first ``.ini`` file under
    ``active_dir`` and read the MACHINE key.

    Returns ``None`` when the active directory is empty or the
    INI has no MACHINE key — the Active panel renders a friendly
    placeholder in that case.
    """
    import configparser

    candidates = sorted(active_dir.glob("*.ini"))
    if not candidates:
        return None

    parser = configparser.ConfigParser()
    try:
        parser.read(candidates[0], encoding="utf-8")
    except (configparser.Error, OSError):
        return None

    if parser.has_option("EMC", "MACHINE"):
        return parser.get("EMC", "MACHINE").strip() or None
    return None


__all__ = [
    "ACTIVE_DIR",
    "DirectoryEntry",
    "MACHINE_CONFIG_DIR",
    "PROFILES_DIR",
    "PROJECT_ROOT",
    "STAGED_DIR",
    "clear_directory",
    "copy_tree",
    "ensure_directories",
    "list_tree",
    "mark_staged_readonly",
    "parse_machine_name",
    "safe_join",
]