import os
import logging
from typing import List
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel
from hardware import execute_sync_cmd, linuxcnc

logger = logging.getLogger("backend.routers.files")

router = APIRouter(prefix="/api/v1/files", tags=["File Management"])

# Absolute path for the nc_files directory
NC_FILES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "nc_files")

# Ensure the directory exists
os.makedirs(NC_FILES_DIR, exist_ok=True)


class LoadProgramRequest(BaseModel):
    """Pydantic model for selecting a G-code file to load into the controller."""
    filename: str


@router.get("", summary="List Files", description="Returns a list of all G-code files in the nc_files directory.")
def list_files():
    """Returns a list of all files in the nc_files directory."""
    try:
        files_list = []
        for filename in os.listdir(NC_FILES_DIR):
            filepath = os.path.join(NC_FILES_DIR, filename)
            if os.path.isfile(filepath):
                files_list.append({
                    "filename": filename,
                    "size_bytes": os.path.getsize(filepath)
                })
        return files_list
    except Exception as e:
        logger.error(f"Failed to list files: {e}")
        raise HTTPException(status_code=500, detail="Failed to list files.")


@router.post("/upload", summary="Upload File", description="Uploads a G-code file to the nc_files directory.")
async def upload_file(file: UploadFile = File(...)):
    """Uploads a G-code file."""
    filepath = os.path.join(NC_FILES_DIR, file.filename)
    try:
        with open(filepath, "wb") as f:
            content = await file.read()
            f.write(content)
        return {"filename": file.filename, "size_bytes": os.path.getsize(filepath)}
    except Exception as e:
        logger.error(f"Failed to upload file {file.filename}: {e}")
        raise HTTPException(status_code=500, detail="Failed to upload file.")


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
