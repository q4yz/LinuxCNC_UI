"""The one file-listing record every file endpoint returns.

G-code programs, profiles, machine files, M-codes and macros all list
their entries in this shape (built by
:class:`mappers.files.FileEntryMapper.FileEntryMapper` from
:class:`domain_file_services.FileService.FileMetadata`), so the
frontend maps every listing through one ``FileEntry`` entity.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class FileEntryResponse(BaseModel):
    """One file or folder below a file root."""

    name: str = Field(..., description="Basename of the entry, extension included")
    path: str = Field(..., description="Forward-slash path relative to the root")
    parent: Optional[str] = Field(
        default=None,
        description="Parent path relative to the root, or null at the top level",
    )
    kind: Literal["file", "folder"] = Field(..., description="'file' or 'folder'")
    size_bytes: int = Field(default=0, description="File size in bytes (0 for folders)")
    modified: Optional[str] = Field(
        default=None,
        description="ISO-8601 timestamp of the last modification",
    )
    read_only: bool = Field(default=False, description="True when the entry must not be edited")
    has_marker: bool = Field(
        default=False,
        description="Profiles only: the file contains the '#Start' marker",
    )


__all__ = ["FileEntryResponse"]
