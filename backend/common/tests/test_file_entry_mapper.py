"""Every file listing returns the same ``FileEntryResponse`` shape."""
from __future__ import annotations

from domain_file_services.FileService import FileMetadata
from mappers.files import FileEntryMapper
from models.FileModels import FileEntryResponse

STANDARD_FIELDS = {"name", "path", "parent", "kind", "size_bytes", "modified", "read_only", "has_marker"}


def test_standard_fields():
    assert set(FileEntryResponse.model_fields) == STANDARD_FIELDS


def test_metadata_maps_one_to_one():
    meta = FileMetadata(
        name="part.ngc",
        path="jobs/part.ngc",
        parent="jobs",
        kind="file",
        size_bytes=42,
        modified="2026-10-09T12:00:00",
        read_only=True,
        has_marker=True,
    )
    assert FileEntryMapper.to_response(meta).model_dump() == {
        "name": "part.ngc",
        "path": "jobs/part.ngc",
        "parent": "jobs",
        "kind": "file",
        "size_bytes": 42,
        "modified": "2026-10-09T12:00:00",
        "read_only": True,
        "has_marker": True,
    }


def test_folder_has_no_size():
    meta = FileMetadata(name="jobs", path="jobs", parent=None, kind="folder")
    entry = FileEntryMapper.to_response(meta)
    assert entry.kind == "folder"
    assert entry.size_bytes == 0
