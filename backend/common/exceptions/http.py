"""Shared HTTP error classes for the FastAPI routers.

The project routers each repeat the same handful of ``HTTPException``
patterns — ``400`` for a bad path, ``404`` for a missing file, ``409``
for a conflict. Centralising the patterns here keeps the response
shape consistent (every operator-facing message lands on the same
``detail`` key the frontend's shared :func:`describeError` knows
about).

The BaseAPIException gives us one place to add a structured ``code``
field later without sweeping every router.

Conventions
-----------

* ``detail`` is always a single sentence. Multi-line failures should
  pass ``exc`` and let ``str(exc)`` render — the
  :func:`describeError` frontend helper joins Pydantic
  ``detail: [ … ]`` arrays with ``"; "`` automatically.
* To chain originating exceptions (previously done via `_from` helpers),
  use native Python syntax: ``raise NotFoundError("...") from exc``.
* Status codes are the FastAPI defaults: ``404`` not-found,
  ``400`` bad-request, ``409`` conflict. Anything outside that
  triple stays a direct ``raise HTTPException(...)`` call so a
  one-off status code (``503`` for offline, ``500`` for last-resort
  catch-all) does not pull this module into noise it cannot fix.
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

__all__ = [
    "BaseAPIException",
    "NotFoundError",
    "BadRequestError",
    "ConflictError",
    "ServiceUnavailableError",
    "register_command_error_handler",
]


class BaseAPIException(HTTPException):
    """Base exception for all standardized API errors.

    Inherits from FastAPI's HTTPException to integrate seamlessly
    with the framework's default exception handlers.
    """
    pass


class NotFoundError(BaseAPIException):
    """A ``404 Not Found`` for a missing entity.

    Args:
        name: Human-readable name of the missing entity — usually
            the file path, profile id, or M-code token. Rendered
            verbatim into the ``detail`` field; callers should keep
            it short (one sentence, no leading "Error:").
    """

    def __init__(self, name: str) -> None:
        super().__init__(status_code=404, detail=name)


class BadRequestError(BaseAPIException):
    """A ``400 Bad Request`` with a plain ``detail`` string.

    Args:
        msg: The operator-facing error message describing why
            the request was invalid.
    """

    def __init__(self, msg: str) -> None:
        super().__init__(status_code=400, detail=msg)


class ConflictError(BaseAPIException):
    """A ``409 Conflict`` for state-mismatch errors.

    The frontend toast layer turns ``409`` into a friendly "no
    program loaded" / "name already exists" surface.

    Args:
        msg: The message the operator reads detailing the conflict.
    """

    def __init__(self, msg: str) -> None:
        super().__init__(status_code=409, detail=msg)

class ServiceUnavailableError(BaseAPIException):
    """A ``503 Service Unavailable`` — a dependency (LinuxCNC, HAL, a
    camera upstream) cannot be reached right now.
    """

    def __init__(self, msg: str) -> None:
        super().__init__(status_code=503, detail=msg)


async def _command_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    status_code = getattr(exc, "status_code", 500)
    return JSONResponse(status_code=status_code, content={"detail": getattr(exc, "detail", str(exc))})


def register_command_error_handler(app: FastAPI) -> None:
    """Answer a hardware :class:`CommandError` with its own status code
    and ``detail`` (the same shape as an ``HTTPException``).

    Imported lazily: the system service uses this module too and must
    not load the LinuxCNC connection package.
    """
    from hardware.Connection.errors import CommandError

    app.add_exception_handler(CommandError, _command_error_handler)
