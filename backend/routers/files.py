import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import List

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from hardware import execute_sync_cmd, linuxcnc

logger = logging.getLogger("backend.routers.files")

router = APIRouter(prefix="/api/v1/ncfiles", tags=["NC Files"])

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
GCODE_DIR = PROJECT_ROOT / "nc_files"
GCODE_DIR.mkdir(parents=True, exist_ok=True)


def _sanitize_filename(filename: str) -> str:
	if not filename:
		raise HTTPException(status_code=400, detail="Filename is required.")

	normalized = filename.replace("\\", "/").split("/")[-1].strip()
	if not normalized or normalized in {".", ".."}:
		raise HTTPException(status_code=400, detail="Invalid filename.")

	return normalized


def _resolve_safe_path(filename: str) -> Path:
	candidate = (GCODE_DIR / filename).resolve()
	try:
		candidate.relative_to(GCODE_DIR.resolve())
	except ValueError as exc:
		raise HTTPException(status_code=400, detail="Invalid file path.") from exc
	return candidate


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
	try:
		files_list: List[FileInfo] = []
		for filepath in sorted(GCODE_DIR.iterdir()):
			if filepath.is_file():
				files_list.append(
					FileInfo(
						filename=filepath.name,
						size_bytes=filepath.stat().st_size,
						modified=datetime.fromtimestamp(filepath.stat().st_mtime).isoformat(),
					)
				)
		return files_list
	except Exception as exc:
		logger.error("Failed to list files: %s", exc)
		raise HTTPException(status_code=500, detail="Failed to list files.")


@router.post(
    "/upload",
    summary="Upload File",
    description="Uploads a G-code file to the nc_files directory.",
    operation_id="uploadFile",
    response_model=UploadFileResponse,
)
def upload_file(file: UploadFile = File(...)) -> UploadFileResponse:
	safe_filename = _sanitize_filename(file.filename)
	filepath = _resolve_safe_path(safe_filename)

	try:
		with open(filepath, "wb") as destination:
			shutil.copyfileobj(file.file, destination)

		return UploadFileResponse(
			status="ok",
			filename=safe_filename,
			message=f"Uploaded {safe_filename} successfully.",
		)
	except Exception as exc:
		logger.error("Failed to upload file %s: %s", safe_filename, exc)
		raise HTTPException(status_code=500, detail="Failed to upload file.")
	finally:
		file.file.close()


@router.delete(
    "/{filename}",
    summary="Delete File",
    description="Deletes a G-code file from the nc_files directory.",
    operation_id="deleteFile",
    response_model=StatusMessageResponse,
)
def delete_file(filename: str) -> StatusMessageResponse:
    """Deletes a G-code file from disk."""
    filepath = GCODE_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="File not found.")

    try:
        filepath.unlink()
        return StatusMessageResponse(status="success", message=f"Deleted {filename}")
    except Exception as exc:
        logger.error(f"Failed to delete file {filename}: {exc}")
        raise HTTPException(status_code=500, detail="Failed to delete file.")


@router.post(
    "/load_program",
    summary="Load G-Code Program",
    description="Loads a previously uploaded G-code file into the LinuxCNC interpreter.",
    operation_id="loadProgram",
    response_model=StatusMessageResponse,
)
def load_program(payload: LoadProgramRequest) -> StatusMessageResponse:
    """Loads a G-code program onto the CNC controller."""
    filepath = GCODE_DIR / payload.filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="File not found.")

    execute_sync_cmd("reset_interpreter")
    execute_sync_cmd("mode", 3, getattr(linuxcnc, "MODE_AUTO", 2))
    execute_sync_cmd("program_open", 5, str(filepath))
    execute_sync_cmd("mode", 3, getattr(linuxcnc, "MODE_MANUAL", 1))
    return StatusMessageResponse(status="success", message=f"Loaded {payload.filename}")
