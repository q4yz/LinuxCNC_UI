import logging
import shutil
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

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
	safe_filename = _sanitize_filename(filename)
	filepath = _resolve_safe_path(safe_filename)

	if not filepath.exists():
		raise HTTPException(status_code=404, detail="File not found.")

	try:
		filepath.unlink()
		return {"status": "ok", "message": f"Deleted {safe_filename}"}
	except Exception as exc:
		logger.error("Failed to delete file %s: %s", safe_filename, exc)
		raise HTTPException(status_code=500, detail="Failed to delete file.")
