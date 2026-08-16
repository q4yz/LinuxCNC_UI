"""Typed HTTP-error class hierarchy.

Re-exports the four FastAPI exception classes that back the old
``raise_*`` helper API. Routers should ``from exceptions import
BadRequestError, ConflictError, NotFoundError`` and raise them
directly (``raise NotFoundError("…") from exc``).
"""
from exceptions.http import (
    BaseAPIException,
    BadRequestError,
    ConflictError,
    NotFoundError,
)

__all__ = [
    "BaseAPIException",
    "BadRequestError",
    "ConflictError",
    "NotFoundError",
]