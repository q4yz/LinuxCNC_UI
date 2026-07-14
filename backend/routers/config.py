import logging
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.config_manager import MachineConfig
from services.hal_compiler import HalCompiler

logger = logging.getLogger("backend.routers.config")
router = APIRouter(prefix="/api/v1/config", tags=["Configuration"])

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MACHINE_CONFIG_DIR = os.path.join(PROJECT_ROOT, "machine_config")
PROFILES_DIR = os.path.join(MACHINE_CONFIG_DIR, "profiles")
READY_DIR = os.path.join(MACHINE_CONFIG_DIR, "ready_for_deploy")
ACTIVE_DIR = os.path.join(MACHINE_CONFIG_DIR, "active")

os.makedirs(PROFILES_DIR, exist_ok=True)
os.makedirs(READY_DIR, exist_ok=True)
os.makedirs(ACTIVE_DIR, exist_ok=True)


class ConfigContent(BaseModel):
    content: str


def _sanitize_profile_filename(filename: str) -> str:
    cleaned = os.path.basename(filename.strip())
    if not cleaned or cleaned in {".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid profile filename.")
    if not cleaned.lower().endswith(".cfg"):
        cleaned = f"{cleaned}.cfg"
    return cleaned


@router.get("", summary="List Config Profiles", description="Returns all profile configuration files from machine_config/profiles.")
def list_configs():
    """List editable source profiles from PROFILES_DIR only."""
    try:
        files_list = []
        for filename in sorted(os.listdir(PROFILES_DIR)):
            filepath = os.path.join(PROFILES_DIR, filename)
            if os.path.isfile(filepath) and filename.lower().endswith(".cfg"):
                files_list.append({
                    "filename": filename,
                    "size_bytes": os.path.getsize(filepath),
                })
        return files_list
    except Exception as exc:
        logger.error("Failed to list config profiles: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to list config profiles.")


@router.get("/{filename}", summary="Read Profile File", description="Returns raw text content of a profile file from machine_config/profiles.")
def read_config(filename: str):
    """Read a profile from PROFILES_DIR only."""
    safe_name = _sanitize_profile_filename(filename)
    filepath = os.path.join(PROFILES_DIR, safe_name)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Config profile not found.")

    try:
        with open(filepath, "r", encoding="utf-8") as handle:
            content = handle.read()
        return {"filename": safe_name, "content": content}
    except Exception as exc:
        logger.error("Failed to read config profile %s: %s", safe_name, exc)
        raise HTTPException(status_code=500, detail="Failed to read config profile.")


@router.post("/{filename}", summary="Save Profile File", description="Overwrites a profile file in machine_config/profiles.")
def save_config(filename: str, payload: ConfigContent):
    """Save profile content to PROFILES_DIR only."""
    safe_name = _sanitize_profile_filename(filename)
    filepath = os.path.join(PROFILES_DIR, safe_name)
    try:
        with open(filepath, "w", encoding="utf-8") as handle:
            handle.write(payload.content)
        return {"status": "ok", "message": f"Saved {safe_name}"}
    except Exception as exc:
        logger.error("Failed to save config profile %s: %s", safe_name, exc)
        raise HTTPException(status_code=500, detail="Failed to save config profile.")


@router.post("/compile/generate/{profile_name}", summary="Generate Staged Configuration", description="Compile a profile into staged LinuxCNC artifacts in ready_for_deploy.")
def compile_generate(profile_name: str):
    """Generate staged outputs from a source profile and return preview text."""
    safe_name = _sanitize_profile_filename(profile_name)
    profile_path = os.path.join(PROFILES_DIR, safe_name)

    try:
        config = MachineConfig(profile_path)
        compiler = HalCompiler(config)
        compiler.generate_staged(safe_name)

        source_cfg_path = os.path.join(READY_DIR, "machine.cfg")
        hal_path = os.path.join(READY_DIR, "machine.hal")
        ini_path = os.path.join(READY_DIR, "linuxcnc.ini")
        json_path = os.path.join(READY_DIR, "remora.json")

        generated_files = {
            "source_cfg": open(source_cfg_path, "r", encoding="utf-8").read() if os.path.exists(source_cfg_path) else "",
            "hal": open(hal_path, "r", encoding="utf-8").read() if os.path.exists(hal_path) else "",
            "ini": open(ini_path, "r", encoding="utf-8").read() if os.path.exists(ini_path) else "",
            "json": open(json_path, "r", encoding="utf-8").read() if os.path.exists(json_path) else "",
        }

        return {
            "status": "ok",
            "files": generated_files,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to compile profile %s: %s", safe_name, exc)
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/compile/deploy", summary="Deploy Staged Configuration", description="Deploy staged files from ready_for_deploy into active.")
def compile_deploy():
    """Deploy staged artifacts to ACTIVE_DIR and return restart-required status."""
    try:
        compiler = HalCompiler(None)
        result = compiler.deploy_to_active()
        return {"status": "ok", "result": result}
    except Exception as exc:
        logger.error("Failed to deploy staged configuration: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to deploy staged configuration.")
