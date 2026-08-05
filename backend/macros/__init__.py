"""Storage for user-authored LinuxCNC macros."""
from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+\.macro$")


class MacroStore:
    """Read and manage macros contained in a single directory."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = (base_dir or Path(__file__).resolve().parent).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        if not name or name.startswith("."):
            raise ValueError("Invalid macro name")
        filename = name if name.endswith(".macro") else f"{name}.macro"
        if not _NAME_RE.fullmatch(filename):
            raise ValueError("Invalid macro name")
        path = (self.base_dir / filename).resolve()
        if not path.is_relative_to(self.base_dir):
            raise ValueError("Invalid macro path")
        return path

    def list(self) -> list[str]:
        return sorted(path.stem for path in self.base_dir.glob("*.macro") if path.is_file())

    def read(self, name: str) -> str:
        return self._path(name).read_text(encoding="utf-8")

    def write(self, name: str, body: str) -> None:
        self._path(name).write_text(body, encoding="utf-8")

    def delete(self, name: str) -> None:
        self._path(name).unlink()
