"""Pydantic models for the macro subsystem (issue #7).

A :class:`Macro` is a hybrid G-code + Python file that the user
edits and runs from the frontend. The parser splits the file into
a list of ``MacroBlock``\s which the executor then walks.

Models are intentionally small: the route handlers do the actual
file I/O; the models are the wire/validation contract.
"""

from __future__ import annotations

from typing import List, Literal, Optional, Union

from pydantic import BaseModel, Field


class MacroSummary(BaseModel):
    """Listing entry returned by ``GET /api/macros``.

    Only the fields the dashboard grid needs are returned; the
    editor fetches the full content on demand.
    """

    name: str = Field(..., description="Macro filename (with .macro extension)")
    modified: str = Field(..., description="ISO-8601 timestamp of last modification")
    size: int = Field(..., description="File size in bytes")


class MacroContent(BaseModel):
    """Full content of a single macro."""

    name: str = Field(..., description="Macro filename (with .macro extension)")
    content: str = Field(..., description="Raw file content (UTF-8 text)")
    modified: str = Field(..., description="ISO-8601 timestamp of last modification")


class MacroSaveRequest(BaseModel):
    """Body of ``PUT /api/macros/{name}``."""

    content: str = Field(..., description="Full macro text to persist")


class MacroLogEntry(BaseModel):
    """Single line in the executor run log."""

    level: Literal["info", "warning", "error"] = Field(
        "info", description="Severity bucket for the UI"
    )
    message: str = Field(..., description="Free-form log message")


class MacroRunResponse(BaseModel):
    """Structured outcome of a macro execution."""

    ok: bool = Field(..., description="True when every block succeeded")
    logs: List[MacroLogEntry] = Field(
        default_factory=list, description="Messages emitted via cnc.log()"
    )
    emitted: List[str] = Field(
        default_factory=list,
        description="G-code lines sent to the controller via cnc.emit()",
    )
    error: Optional[str] = Field(
        default=None,
        description="Traceback string when a Python block raised; null on success",
    )


# Internal parser artefact. Not part of the wire schema but kept in
# this module so the parser and the executor share the same type.
MacroBlock = Union[
    dict,  # {"kind": "gcode", "text": "G21\n..."}
    dict,  # {"kind": "python", "code": "for x in ..."}
]


__all__ = [
    "MacroSummary",
    "MacroContent",
    "MacroSaveRequest",
    "MacroLogEntry",
    "MacroRunResponse",
]
