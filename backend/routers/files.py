"""``/api/v1/ncfiles`` HTTP surface.

Thin wrapper around :class:`ProgramFileService` for the file-CRUD
endpoints (``list``, ``upload``, ``delete``). The
``load_program`` flow keeps its original shape because wrapping
the ``linuxcnc.execute_sync_cmd`` calls behind a
:class:`ProgramLoader` service is explicitly out of scope for
this pass — the body of the handler is marked with a ``TODO``
that points to the follow-up.

All filesystem calls are funneled through the service. The
``os``/``shutil`` imports are gone; the helper that used to
normalize ``\\`` and split on ``/`` now lives in
:meth:`ProgramFileService.safe_join` so the path-safety contract
stays single-sourced.
"""

import logging
from typing import List

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from hardware import execute_sync_cmd, linuxcnc
from services import ProgramFileService, get_program_service

logger = logging.getLogger("backend.routers.files")

router = APIRouter(prefix="/api/v1/ncfiles", tags=["NC Files"])


class LoadProgramRequest(BaseModel):
    """Pydantic model for selecting a G-code file to load into the controller."""

    filename: str = Field(..., description="Name of the uploaded G-code file to load into the interpreter")


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


@router.post(
    "/load_program",
    summary="Load G-Code Program",
    description="Loads a previously uploaded G-code file into the LinuxCNC interpreter.",
    operation_id="loadProgram",
    response_model=StatusMessageResponse,
)
def load_program(payload: LoadProgramRequest) -> StatusMessageResponse:
    """Loads a G-code program onto the CNC controller.

    TODO(issue #49 follow-up): the ``linuxcnc.execute_sync_cmd``
    flow stays in the router for now; the next pass should wrap
    it in a thin :class:`ProgramLoader` service that owns the
    ``reset_interpreter`` / ``mode`` / ``program_open`` sequence
    so this endpoint is a one-liner like the rest.
    """
    service: ProgramFileService = get_program_service()
    try:
        filepath = service.resolve_program_path(payload.filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid file path.") from exc

    if not filepath.exists() or not filepath.is_file():
        raise HTTPException(status_code=404, detail="File not found.")

    execute_sync_cmd("reset_interpreter")
    execute_sync_cmd("mode", 3, getattr(linuxcnc, "MODE_AUTO", 2))
    execute_sync_cmd("program_open", 5, str(filepath))
    execute_sync_cmd("mode", 3, getattr(linuxcnc, "MODE_MANUAL", 1))
    return StatusMessageResponse(status="success", message=f"Loaded {payload.filename}")
