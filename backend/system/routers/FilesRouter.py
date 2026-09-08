"""``/api/v1/programs`` HTTP surface.

Thin wrapper around :class:`ProgramFileService` for the file-CRUD
endpoints (``list``, ``upload``, ``delete``, ``content``). The
``load_program`` flow keeps its original shape because wrapping
the ``linuxcnc.execute_sync_cmd`` calls behind a
:class:`ProgramLoader` service is explicitly out of scope for
this pass â€” the body of the handler is marked with a ``TODO``
that points to the follow-up.

All filesystem calls are funneled through the service. The
``os``/``shutil`` imports are gone; the helper that used to
normalize ``\\`` and split on ``/`` now lives in
:meth:`ProgramFileService.safe_join` so the path-safety contract
stays single-sourced.

Endpoint naming follows the same pattern as the machineconfig
module:

    GET    /api/v1/programs                   â€” list files
    POST   /api/v1/programs/upload           â€” upload file
    DELETE /api/v1/programs/{filename}       â€” delete file
    GET    /api/v1/programs/content/{filename} â€” read file content
    PUT    /api/v1/programs/content/{filename} â€” write file content
    POST   /api/v1/programs/load_program     â€” load program into controller
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from services import ProgramFileService, get_program_service
from services.gcode_thumbnail import extract_thumbnail

logger = logging.getLogger("backend.routers.files")

router = APIRouter(prefix="/api/v1/programs", tags=["Program Files"])

# Slicer thumbnails always live in the first few KB of the file, well
# below this cap — the head-scan never loads multi-MB programs.
THUMBNAIL_HEAD_BYTES = 512 * 1024


class FileInfo(BaseModel):
    """Metadata describing a single G-code file on disk."""

    filename: str = Field(..., description="Filename (basename, no path)")
    size_bytes: int = Field(..., description="File size in bytes")
    modified: str = Field(..., description="ISO-8601 timestamp of the last modification")


class UploadFileResponse(BaseModel):
    """Response returned after a successful file upload."""

    status: str = Field(..., description="Outcome summary (e.g., 'ok')")
    filename: str = Field(..., description="Sanitized filename that was stored on disk")
    message: str = Field(..., description="Human-readable upload confirmation")


class StatusMessageResponse(BaseModel):
    """Response containing a status string and an informational message."""

    status: str = Field(..., description="Outcome summary (e.g., 'success')")
    message: str = Field(..., description="Human-readable confirmation message")


class FileThumbnailResponse(BaseModel):
    """Largest slicer-embedded thumbnail found in a G-code file.

    ``data_url`` is ``None`` when the file carries no embedded
    thumbnail (the frontend then shows a generic icon).
    """

    data_url: Optional[str] = Field(
        None,
        description="'data:image/png;base64,…' URL for an <img> tag, or None when the file has no embedded thumbnail.",
    )
    width: Optional[int] = Field(None, description="Embedded thumbnail width in pixels.")
    height: Optional[int] = Field(None, description="Embedded thumbnail height in pixels.")


@router.get(
    "",
    summary="List Files",
    description="Returns a list of all G-code files in the nc_files directory.",
    operation_id="listFiles",
    response_model=List[FileInfo],
)
def list_files() -> List[FileInfo]:
    """List G-code files via :class:`ProgramFileService`."""
    try:
        service: ProgramFileService = get_program_service()
        return [
            FileInfo(
                filename=entry.name,
                size_bytes=entry.size_bytes,
                modified=entry.modified or "",
            )
            for entry in service.list_program_files()
        ]
    except Exception as exc:  # noqa: BLE001 - last-resort guard
        logger.error("Failed to list files: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to list files.") from exc


@router.post(
    "/upload",
    summary="Upload File",
    description="Uploads a G-code file to the nc_files directory.",
    operation_id="uploadFile",
    response_model=UploadFileResponse,
)
def upload_file(file: UploadFile = File(...)) -> UploadFileResponse:
    """Persist an uploaded G-code file via :class:`ProgramFileService`."""
    service: ProgramFileService = get_program_service()
    try:
        # Normalise the filename through the service so ``\`` segments
        # and ``..`` traversal are rejected the same way as a direct
        # ``safe_join`` call would reject them.
        safe_filename = service.safe_join(file.filename or "").name
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid filename.") from exc

    try:
        payload = file.file.read()
        service.save_upload(safe_filename, payload)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - last-resort guard
        logger.error("Failed to upload file %s: %s", safe_filename, exc)
        raise HTTPException(status_code=500, detail="Failed to upload file.") from exc
    finally:
        file.file.close()

    return UploadFileResponse(
        status="ok",
        filename=safe_filename,
        message=f"Uploaded {safe_filename} successfully.",
    )


@router.delete(
    "/{filename}",
    summary="Delete File",
    description="Deletes a G-code file from the nc_files directory.",
    operation_id="deleteFile",
    response_model=StatusMessageResponse,
)
def delete_file(filename: str) -> StatusMessageResponse:
    """Delete a G-code file via :class:`ProgramFileService`."""
    service: ProgramFileService = get_program_service()
    try:
        service.delete_file(filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="File not found.") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - last-resort guard
        logger.error("Failed to delete file %s: %s", filename, exc)
        raise HTTPException(status_code=500, detail="Failed to delete file.") from exc
    return StatusMessageResponse(status="success", message=f"Deleted {filename}")


@router.get(
    "/thumbnail/{filename}",
    summary="Get File Thumbnail",
    description=(
        "Extracts the largest slicer-embedded thumbnail (the "
        "'; thumbnail begin/end' base64 comment block that Cura / "
        "PrusaSlicer / OrcaSlicer write at the top of the file). Only "
        "the first 512 KB of the file is scanned, so multi-megabyte "
        "programs cost nothing to preview. Returns data_url=None for "
        "files without an embedded thumbnail."
    ),
    operation_id="getFileThumbnail",
    response_model=FileThumbnailResponse,
)
def get_file_thumbnail(filename: str) -> FileThumbnailResponse:
    """Extract the slicer-embedded thumbnail via head-scan.

    Errors map to actionable HTTP statuses:

    * ``ValueError`` (path-safety violation) → ``400``
    * ``FileNotFoundError`` → ``404``
    * any other unexpected error → ``500``
    """
    service: ProgramFileService = get_program_service()
    try:
        head = service.read_head(filename, THUMBNAIL_HEAD_BYTES)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid file path.") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="File not found.") from exc
    except Exception as exc:  # noqa: BLE001 - last-resort guard
        logger.error("Failed to read file head %s: %s", filename, exc)
        raise HTTPException(status_code=500, detail="Failed to read file.") from exc

    thumb = extract_thumbnail(head.decode("utf-8", errors="ignore"))
    return FileThumbnailResponse(**(thumb or {}))


@router.get(
    "/content/{filename}",
    summary="Read File Content",
    description=(
        "Returns the raw text content of a G-code file. Used by the "
        "frontend to populate the editor when the user clicks Edit."
    ),
    operation_id="readFile",
    response_model=str,
)
def read_file(filename: str) -> str:
    """Read a G-code file's text content via :class:`ProgramFileService`.

    Errors map to actionable HTTP statuses:

    * ``ValueError`` (path-safety violation) â†’ ``400``
    * ``FileNotFoundError`` â†’ ``404``
    * any other unexpected error â†’ ``500``
    """
    service: ProgramFileService = get_program_service()
    try:
        return service.read_file(filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid file path.") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="File not found.") from exc
    except Exception as exc:  # noqa: BLE001 - last-resort guard
        logger.error("Failed to read file %s: %s", filename, exc)
        raise HTTPException(status_code=500, detail="Failed to read file.") from exc


class GCodeContentPayload(BaseModel):
    """Body of ``PUT /api/v1/programs/content/{filename}``."""

    content: str = Field(
        ...,
        description="Full UTF-8 text content of the G-code file.",
    )


@router.put(
    "/content/{filename}",
    summary="Write File Content",
    description=(
        "Overwrite the text content of a G-code file. Mirrors the "
        "machineconfig ``PUT /profiles/content/{path}`` shape so the "
        "frontend editor can use one code path for both kinds of "
        "file."
    ),
    operation_id="writeFile",
    response_model=StatusMessageResponse,
)
def write_file(filename: str, payload: GCodeContentPayload) -> StatusMessageResponse:
    """Overwrite a G-code file's text content via :class:`ProgramFileService`.

    Errors map to actionable HTTP statuses:

    * ``ValueError`` (path-safety violation) â†’ ``400``
    * ``FileNotFoundError`` â†’ ``404``
    * ``PermissionError`` (read-only file) â†’ ``403``
    * any other unexpected error â†’ ``500``
    """
    service: ProgramFileService = get_program_service()
    try:
        service.write_file(filename, payload.content, overwrite=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid file path.") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="File not found.") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - last-resort guard
        logger.error("Failed to write file %s: %s", filename, exc)
        raise HTTPException(status_code=500, detail="Failed to write file.") from exc
    return StatusMessageResponse(status="success", message=f"Saved {filename}")
