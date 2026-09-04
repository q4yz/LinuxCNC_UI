"""
Per-module persistent settings store.

SettingsStore is the canonical persistence layer for module settings
defined in ``.agent/contracts/settings-module.md``. Each module owns one
file at ``<data_root>/modules/<module_id>/settings.json``.

Key properties:

* **Atomic write.** Persisting settings writes to ``settings.json.tmp``
  first and then atomically renames the file with
  :func:`os.replace`. A process crash mid-write leaves the existing
  ``settings.json`` intact; a fresh checkout finds no ``settings.json``
  and falls back to Pydantic defaults.

* **In-memory cache.** Reads return cached values without re-parsing
  the file. Every PUT invalidates the cache so the next read sees the
  freshly persisted values.

* **Default fallback.** On the first call to :meth:`read_all`, the
  store reads ``defaults`` (typically a Pydantic model instance) and
  returns ``defaults.model_dump()``. The store never assumes a schema
  beyond "JSON object" — modules own their validation.

The store is intentionally framework-agnostic: it does not import
FastAPI or Pydantic validators. Validation is the module's job; the
store's job is to make the bytes durable.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class SettingsStore:
    """Filesystem-backed JSON settings store for a single module.

    Args:
        module_id: The module's unique identifier. Forms the directory
            name under ``data_root``.
        data_root: Root directory. Settings live at
            ``<data_root>/modules/<module_id>/settings.json``. The
            directory is created on first write.
        defaults: A Pydantic model instance (or ``None``) whose
            ``model_dump()`` is returned when ``settings.json`` is
            missing. Defaults are merged into the persisted payload
            so modules can introduce new keys without breaking older
            deployments.
    """

    FILENAME = "settings.json"

    def __init__(
        self,
        module_id: str,
        data_root: Path,
        defaults: Optional[BaseModel] = None,
    ) -> None:
        if not module_id or not isinstance(module_id, str):
            raise ValueError("module_id must be a non-empty string")
        self.module_id = module_id
        self._data_root = Path(data_root)
        self._defaults = defaults
        self._path = self._data_root / "modules" / module_id / self.FILENAME
        self._cache: Optional[Dict[str, Any]] = None
        # A module-local lock keeps concurrent PUTs on the same module
        # from racing the tmp -> replace sequence. Cross-module writes
        # are independent because each module owns its own file.
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        """Absolute path of the ``settings.json`` file."""
        return self._path

    def read_all(self) -> Dict[str, Any]:
        """Return the persisted settings, falling back to defaults.

        Returns:
            A dict that is safe to mutate (the store hands out a fresh
            shallow copy on every call so caller mutations cannot leak
            back into the cache).
        """
        if self._cache is not None:
            return dict(self._cache)

        with self._lock:
            # Re-check after acquiring the lock to avoid a TOCTOU race
            # where two readers miss the cache and double-load.
            if self._cache is not None:
                return dict(self._cache)

            if self._path.exists():
                try:
                    with self._path.open(encoding="utf-8") as fp:
                        loaded = json.load(fp)
                except (OSError, json.JSONDecodeError) as exc:
                    logger.error(
                        "SettingsStore %s: failed to read %s: %s. "
                        "Falling back to defaults.",
                        self.module_id,
                        self._path,
                        exc,
                    )
                    loaded = {}
            else:
                loaded = {}

            merged = self._merge_defaults(loaded)
            self._cache = merged
            return dict(merged)

    def read_key(self, key: str) -> Any:
        """Return a single settings key, or ``None`` if not set."""
        data = self.read_all()
        return data.get(key)

    def write_all(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Replace the entire settings payload atomically.

        Args:
            payload: New settings dict. Values are persisted verbatim
                (no Pydantic re-validation — the module owns schema).

        Returns:
            The merged payload (defaults + persisted + new) that is now
            stored on disk and cached in memory.
        """
        if not isinstance(payload, dict):
            raise TypeError(
                f"SettingsStore {self.module_id}: payload must be a dict, "
                f"got {type(payload).__name__}"
            )

        with self._lock:
            merged = self._merge_defaults(payload)
            self._atomic_write(merged)
            self._cache = merged
            return dict(merged)

    def write_key(self, key: str, value: Any) -> Dict[str, Any]:
        """Upsert a single key and persist the resulting payload.

        Args:
            key: Setting name.
            value: New value (any JSON-serialisable type).

        Returns:
            The merged payload after the upsert.
        """
        current = self.read_all()
        current[key] = value
        return self.write_all(current)

    def invalidate(self) -> None:
        """Force the next :meth:`read_all` to re-read from disk."""
        with self._lock:
            self._cache = None

    def _merge_defaults(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Merge ``payload`` on top of the Pydantic defaults.

        Defaults provide forward-compatibility: when a module is
        upgraded with new settings keys, existing deployments continue
        to work because the defaults fill in missing keys. User-set
        values always win over defaults.
        """
        if self._defaults is None:
            return dict(payload)
        base = self._defaults.model_dump()
        base.update(payload)
        return base

    def _atomic_write(self, payload: Dict[str, Any]) -> None:
        """Write ``payload`` to ``settings.json`` via tmp + os.replace.

        The write is atomic on POSIX filesystems: ``os.replace`` is
        guaranteed to be atomic, so a process crash mid-write either
        leaves the previous ``settings.json`` intact (if the rename
        hasn't happened yet) or the new file in place — never a
        half-written file.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)

        # ``delete=False`` so we can rename onto a Windows-friendly
        # path; ``dir=`` pins the temp file to the same filesystem as
        # ``settings.json`` so the rename stays atomic.
        fd, tmp_path = tempfile.mkstemp(
            prefix=".settings-",
            suffix=".json.tmp",
            dir=str(self._path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fp:
                json.dump(payload, fp, indent=2, sort_keys=True)
                fp.write("\n")
                fp.flush()
                os.fsync(fp.fileno())
            os.replace(tmp_path, self._path)
        except Exception:
            # Best-effort cleanup of the temp file on failure; never
            # raise from cleanup because we want the original error to
            # propagate.
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


__all__ = ["SettingsStore"]