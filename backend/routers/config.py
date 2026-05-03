import os
import logging
from typing import List
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel

# Import the standalone parsing service
from services.klipper_parser import translate_klipper_to_linuxcnc

logger = logging.getLogger("backend.routers.config")
router = APIRouter(prefix="/api/v1/config", tags=["Configuration"])

# Absolute path for the machine_config directory
CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "machine_config")
os.makedirs(CONFIG_DIR, exist_ok=True)

class ConfigContent(BaseModel):
    content: str

@router.get("", summary="List Config Files", description="Returns a list of all configuration files in the machine_config directory.")
def list_configs():
    """Returns a list of all files in the machine_config directory."""
    try:
        files_list = []
        for filename in os.listdir(CONFIG_DIR):
            filepath = os.path.join(CONFIG_DIR, filename)
            if os.path.isfile(filepath):
                files_list.append({
                    "filename": filename,
                    "size_bytes": os.path.getsize(filepath)
                })
        return files_list
    except Exception as e:
        logger.error(f"Failed to list config files: {e}")
        raise HTTPException(status_code=500, detail="Failed to list config files.")


@router.post("/parse", summary="Parse Klipper Configs", description="Triggers a background task to parse Klipper configs into LinuxCNC formats.")
def parse_configs(background_tasks: BackgroundTasks):
    """Triggers the heavy parsing service in the background."""
    logger.info("Triggering background config parser.")
    background_tasks.add_task(translate_klipper_to_linuxcnc, CONFIG_DIR)
    return {"status": "parsing started"}


@router.get("/{filename}", summary="Read Config File", description="Returns the raw text content of a config file.")
def read_config(filename: str):
    """Reads a configuration file."""
    filepath = os.path.join(CONFIG_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Config file not found.")
    
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        return {"filename": filename, "content": content}
    except Exception as e:
        logger.error(f"Failed to read config {filename}: {e}")
        raise HTTPException(status_code=500, detail="Failed to read file.")


@router.post("/{filename}", summary="Save Config File", description="Overwrites a configuration file with new raw text.")
def save_config(filename: str, payload: ConfigContent):
    """Saves text content to a configuration file."""
    filepath = os.path.join(CONFIG_DIR, filename)
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(payload.content)
        return {"status": "success", "message": f"Saved {filename}"}
    except Exception as e:
        logger.error(f"Failed to save config {filename}: {e}")
        raise HTTPException(status_code=500, detail="Failed to save file.")
