"""Crash-safe JSON file writes, shared by every settings store.

Extracted from the former per-module ``SettingsStore._atomic_write`` so
the UI settings store keeps the exact same durability guarantee.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_json(path: Path, payload: Any) -> None:
    """Write ``payload`` to ``path`` via a temp file + ``os.replace``.

    ``os.replace`` is atomic, so a crash mid-write leaves either the
    previous file or the new one in place — never a half-written file.
    Readers in other processes (``ui_settings_reader``) therefore always
    see a complete document.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # ``dir=`` pins the temp file to the same filesystem so the rename
    # stays atomic (also on Windows).
    fd, tmp_path = tempfile.mkstemp(prefix=f".{path.stem}-", suffix=".json.tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            json.dump(payload, fp, indent=2, sort_keys=True)
            fp.write("\n")
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(tmp_path, path)
    except Exception:
        # Best-effort cleanup; never mask the original error.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


__all__ = ["atomic_write_json"]
