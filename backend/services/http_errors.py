"""Shared HTTP error helpers for the FastAPI routers.

The project routers each repeat the same handful of ``HTTPException``
patterns — ``400`` for a bad path, ``404`` for a missing file, ``409``
for a conflict. Centralising the patterns here keeps the response
shape consistent (every operator-facing message lands on the same
``detail`` key the frontend's shared :func:`describeError` knows
about) and gives us one place to add a structured ``code`` field
later without sweeping every router.

The three core helpers are intentionally small and free of side
effects — each one is a thin wrapper over ``fastapi.HTTPException``
that pre-fills the status code and adds the right key. Use them
when the message is operator-facing; for domain validation errors
that already raise ``ConfigValidationError`` (issue #99), keep the
existing exception path — those need the structured envelope, not
the simple ``detail`` string.

Conventions
-----------

* ``detail`` is always a single sentence. Multi-line failures should
  pass ``exc`` and let ``str(exc)`` render — the
  :func:`describeError` frontend helper joins Pydantic
  ``detail: [ … ]`` arrays with ``"; "`` automatically.
* The exception is raised, not returned. Callers do not need to
  ``return raise_...``; the function never returns.
* Status codes are the FastAPI defaults: ``404`` not-found,
  ``400`` bad-request, ``409`` conflict. Anything outside that
  triple stays a direct ``raise HTTPException(...)`` call so a
  one-off status code (``503`` for offline, ``500`` for last-resort
  catch-all) does not pull this module into noise it cannot fix.
"""
from __future__ import annotations

from fastapi import HTTPException


__all__ = [
    "raise_not_found",
    "raise_bad_request",
    "raise_conflict",
    "raise_not_found_from",
    "raise_bad_request_from",
    "raise_conflict_from",
]


def raise_not_found(name: str) -> None:
    """Raise a ``404 Not Found`` for a missing entity.

    Args:
        name: Human-readable name of the missing entity — usually
            the file path, profile id, or M-code token. Rendered
            verbatim into the ``detail`` field; callers should keep
            it short (one sentence, no leading "Error:").
    """
    raise HTTPException(status_code=404, detail=name)


def raise_bad_request(msg: str) -> None:
    """Raise a ``400 Bad Request`` with a plain ``detail`` string."""
    raise HTTPException(status_code=400, detail=msg)


def raise_conflict(msg: str) -> None:
    """Raise a ``409 Conflict`` for state-mismatch errors.

    The frontend toast layer turns ``409`` into a friendly "no
    program loaded" / "name already exists" surface. The ``detail``
    is the message the operator reads.
    """
    raise HTTPException(status_code=409, detail=msg)


def raise_not_found_from(name: str, exc: BaseException) -> None:
    """``raise_not_found`` that chains the originating exception.

    The wire response is identical to :func:`raise_not_found`; the
    ``__cause__`` chain only affects server-side logging and
    tracebacks. Useful at the boundary where a storage-layer
    exception (``ValueError`` from ``safe_join`` etc.) is translated
    to a 404 — the underlying call is preserved for debugging.
    """
    try:
        raise HTTPException(status_code=404, detail=name)
    except HTTPException:
        raise HTTPException(status_code=404, detail=name) from exc


def raise_bad_request_from(msg: str, exc: BaseException) -> None:
    """``raise_bad_request`` that chains the originating exception."""
    try:
        raise HTTPException(status_code=400, detail=msg)
    except HTTPException:
        raise HTTPException(status_code=400, detail=msg) from exc


def raise_conflict_from(msg: str, exc: BaseException) -> None:
    """``raise_conflict`` that chains the originating exception."""
    try:
        raise HTTPException(status_code=409, detail=msg)
    except HTTPException:
        raise HTTPException(status_code=409, detail=msg) from exc
