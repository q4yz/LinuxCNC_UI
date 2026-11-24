"""A random secret both backends share through a file in ``backend/data``.

Created on first use, readable by the owner only. Two backends starting
together agree on one value (exclusive create).
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def read_or_create(path: Path) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    except OSError:
        pass
    value = secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return path.read_text(encoding="utf-8").strip()
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(value)
    return value


__all__ = ["DATA_DIR", "read_or_create"]
