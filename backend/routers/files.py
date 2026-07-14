import logging
import shutil
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from typing import List
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel
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
    filename: str


@router.get("", summary="List Files", description="Returns a list of all G-code files in the nc_files directory.")
def list_files():
	try:
		files_list = []
		for filepath in sorted(GCODE_DIR.iterdir()):
			if filepath.is_file():
				files_list.append(
					{
						"filename": filepath.name,
						"size_bytes": filepath.stat().st_size,
						"modified": datetime.fromtimestamp(filepath.stat().st_mtime).isoformat(),
					}
				)
		return files_list
	except Exception as exc:
		logger.error("Failed to list files: %s", exc)
		raise HTTPException(status_code=500, detail="Failed to list files.")


@router.post("/upload", summary="Upload File", description="Uploads a G-code file to the nc_files directory.")
def upload_file(file: UploadFile = File(...)):
	safe_filename = _sanitize_filename(file.filename)
	filepath = _resolve_safe_path(safe_filename)

	try:
		with open(filepath, "wb") as destination:
			shutil.copyfileobj(file.file, destination)

		return {"status": "ok", "filename": safe_filename, "message": f"Uploaded {safe_filename} successfully."}
	except Exception as exc:
		logger.error("Failed to upload file %s: %s", safe_filename, exc)
		raise HTTPException(status_code=500, detail="Failed to upload file.")
	finally:
		file.file.close()


@router.delete("/{filename}", summary="Delete File", description="Deletes a G-code file from the nc_files directory.")
def delete_file(filename: str):
    """Deletes a G-code file from disk."""
    filepath = os.path.join(NC_FILES_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="File not found.")

    try:
        os.remove(filepath)
        return {"status": "success", "message": f"Deleted {filename}"}
    except Exception as e:
        logger.error(f"Failed to delete file {filename}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete file.")


@router.post("/load_program", summary="Load G-Code Program", description="Loads a previously uploaded G-code file into the LinuxCNC interpreter.")
def load_program(payload: LoadProgramRequest):
    """Loads a G-code program onto the CNC controller."""
    filepath = os.path.join(NC_FILES_DIR, payload.filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="File not found.")

    execute_sync_cmd("reset_interpreter")
    execute_sync_cmd("mode", 3, getattr(linuxcnc, "MODE_AUTO", 2))
    res = execute_sync_cmd("program_open", 5, filepath)
    execute_sync_cmd("mode", 3, getattr(linuxcnc, "MODE_MANUAL", 1))
    return res
