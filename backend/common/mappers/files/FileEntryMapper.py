from __future__ import annotations

from typing import TYPE_CHECKING, Iterable, List

from models.FileModels import FileEntryResponse

if TYPE_CHECKING:
    from domain_file_services.FileService import FileMetadata


class FileEntryMapper:
    """``FileMetadata`` (any file root) → the shared ``FileEntryResponse``."""

    @classmethod
    def to_response(cls, entry: "FileMetadata") -> FileEntryResponse:
        return FileEntryResponse(
            name=entry.name,
            path=entry.path,
            parent=entry.parent,
            kind="folder" if entry.kind == "folder" else "file",
            size_bytes=entry.size_bytes,
            modified=entry.modified,
            read_only=entry.read_only,
            has_marker=entry.has_marker,
        )

    @classmethod
    def to_responses(cls, entries: Iterable["FileMetadata"]) -> List[FileEntryResponse]:
        return [cls.to_response(entry) for entry in entries]
