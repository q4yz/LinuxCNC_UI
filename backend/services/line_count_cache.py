"""Backend line-count cache.

Real LinuxCNC's ``linuxcnc.stat`` object exposes ``current_line``
and ``motion_line`` but never a total-line counter — the
interpreter does not know how many lines the loaded file has
until something counts them. We count the file once at
``program_open`` time and stash the result here so the snapshot
endpoint (``routers/base_thread.py``) and the dedicated progress
endpoint (``modules/program/router.py``) can both answer without
re-reading the file on every poll.

The cache is process-local and intentionally tiny: only the
currently loaded file is meaningful, but the router does not
enforce single-entry state so a multi-file batch remains
representable. ``unregister_all`` drops the entire map so the
aborts / unloads paths can clear the slate without enumerating
individual keys.

Concurrency: the cache is mutated from the synchronous
``load_program`` / ``unload_program`` paths and read from the
HTTP request thread / WebSocket loop. Python's GIL makes each
``dict[k] = v`` and ``dict.get`` atomic, so no lock is required —
a stale or partial value would only surface a wrong ``total_lines``
for at most one tick of the 1 Hz snapshot, and the next load
overwrites it anyway.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict

logger = logging.getLogger("backend.services.line_count_cache")

# Absolute file path -> line count.
_CACHE: Dict[str, int] = {}


def register(path: str, count: int) -> None:
    """Cache the line count for ``path``.

    Called from :func:`backend.modules.program.router.load_program`
    after the interpreter has committed ``stat.file``. We trust the
    caller's count rather than re-reading the file here so the
    hot path stays in the program router.
    """
    if not path:
        return
    _CACHE[path] = max(0, int(count))


def lookup(path: str) -> int:
    """Return the cached line count for ``path`` or ``0`` if absent.

    A missing / empty path returns ``0`` so callers can blindly feed
    ``stat.file`` into this helper without a None check.
    """
    if not path:
        return 0
    return _CACHE.get(path, 0)


def unregister_all() -> None:
    """Drop every cached line count.

    Called from :func:`backend.modules.program.router.unload_program`
    (and any abort path) so a follow-up ``/progress`` hit cannot
    surface a stale total for a file that is no longer loaded.
    """
    _CACHE.clear()


def count_lines(path: str) -> int:
    """Count the lines in ``path`` for use at ``register`` time.

    Centralised here so the program router doesn't have to know
    about :mod:`pathlib`; the helper swallows ``OSError`` and
    returns ``0`` so a missing / unreadable file fails soft (the
    frontend's progress bar will just stay at 0 %).
    """
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning("Could not count lines in %s: %s", path, exc)
        return 0
    if not text:
        return 0
    # ``splitlines`` swallows the trailing newline of the last line,
    # matching LinuxCNC's own line-counter convention.
    return len(text.splitlines())


__all__ = ["register", "lookup", "unregister_all", "count_lines"]
