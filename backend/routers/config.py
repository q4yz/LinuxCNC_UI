import logging
import os
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

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
    """Pydantic model for the body of POST /config/{filename}."""
    content: str = Field(..., description="Raw text content to overwrite the profile file with")


class ConfigProfileInfo(BaseModel):
    """Metadata describing a single editable profile file."""
    filename: str = Field(..., description="Filename (basename, no path)")
    size_bytes: int = Field(..., description="File size in bytes")


class ConfigFileContent(BaseModel):
    """Response model for GET /config/{filename}."""
    filename: str = Field(..., description="Sanitized filename that was read")
    content: str = Field(..., description="Raw text content of the profile file")


class StatusMessageResponse(BaseModel):
    """Generic response model containing a status string and an informational message."""
    status: str = Field(..., description="Outcome summary (e.g., 'ok')")
    message: str = Field(..., description="Human-readable confirmation message")


class GeneratedFiles(BaseModel):
    """Previews of the staged configuration artifacts emitted by the compiler."""
    source_cfg: str = Field(default="", description="Generated machine.cfg source preview")
    hal: str = Field(default="", description="Generated machine.hal preview")
    ini: str = Field(default="", description="Generated linuxcnc.ini preview")
    json: str = Field(default="", description="Generated remora.json preview")


class CompileGenerateResponse(BaseModel):
    """Response model for the legacy /config/compile/generate endpoint."""
    status: str = Field(..., description="Outcome summary (e.g., 'ok')")
    files: GeneratedFiles = Field(..., description="Preview text of each generated artifact")


class CompileDeployResponse(BaseModel):
    """Response model for the legacy /config/compile/deploy endpoint."""
    status: str = Field(..., description="Outcome summary (e.g., 'ok')")
    result: Dict[str, Any] = Field(..., description="Compiler-reported deployment result details")


def _sanitize_profile_filename(filename: str) -> str:
    cleaned = os.path.basename(filename.strip())
    if not cleaned or cleaned in {".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid profile filename.")
    if not cleaned.lower().endswith(".cfg"):
        cleaned = f"{cleaned}.cfg"
    return cleaned


@router.get(
    "",
    summary="List Config Profiles",
    description="Returns all profile configuration files from machine_config/profiles.",
    operation_id="listConfigs",
    response_model=List[ConfigProfileInfo],
)
def list_configs() -> List[ConfigProfileInfo]:
    """List editable source profiles from PROFILES_DIR only."""
    try:
        files_list: List[ConfigProfileInfo] = []
        for filename in sorted(os.listdir(PROFILES_DIR)):
            filepath = os.path.join(PROFILES_DIR, filename)
            if os.path.isfile(filepath) and filename.lower().endswith(".cfg"):
                files_list.append(
                    ConfigProfileInfo(
                        filename=filename,
                        size_bytes=os.path.getsize(filepath),
                    )
                )
        return files_list
    except Exception as exc:
        logger.error("Failed to list config profiles: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to list config profiles.")


@router.get(
    "/{filename}",
    summary="Read Profile File",
    description="Returns raw text content of a profile file from machine_config/profiles.",
    operation_id="readConfig",
    response_model=ConfigFileContent,
)
def read_config(filename: str) -> ConfigFileContent:
    """Read a profile from PROFILES_DIR only."""
    safe_name = _sanitize_profile_filename(filename)
    filepath = os.path.join(PROFILES_DIR, safe_name)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Config profile not found.")

    try:
        with open(filepath, "r", encoding="utf-8") as handle:
            content = handle.read()
        return ConfigFileContent(filename=safe_name, content=content)
    except Exception as exc:
        logger.error("Failed to read config profile %s: %s", safe_name, exc)
        raise HTTPException(status_code=500, detail="Failed to read config profile.")


@router.post(
    "/{filename}",
    summary="Save Profile File",
    description="Overwrites a profile file in machine_config/profiles.",
    operation_id="saveConfig",
    response_model=StatusMessageResponse,
)
def save_config(filename: str, payload: ConfigContent) -> StatusMessageResponse:
    """Save profile content to PROFILES_DIR only."""
    safe_name = _sanitize_profile_filename(filename)
    filepath = os.path.join(PROFILES_DIR, safe_name)
    try:
        with open(filepath, "w", encoding="utf-8") as handle:
            handle.write(payload.content)
        return StatusMessageResponse(status="ok", message=f"Saved {safe_name}")
    except Exception as exc:
        logger.error("Failed to save config profile %s: %s", safe_name, exc)
        raise HTTPException(status_code=500, detail="Failed to save config profile.")


@router.post(
    "/compile/generate/{profile_name}",
    summary="Generate Staged Configuration",
    description="Compile a profile into staged LinuxCNC artifacts in ready_for_deploy.",
    operation_id="compileGenerateLegacy",
    response_model=CompileGenerateResponse,
)
def compile_generate(profile_name: str) -> CompileGenerateResponse:
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

        def _read_or_empty(path: str) -> str:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as handle:
                    return handle.read()
            return ""

        generated_files = GeneratedFiles(
            source_cfg=_read_or_empty(source_cfg_path),
            hal=_read_or_empty(hal_path),
            ini=_read_or_empty(ini_path),
            json=_read_or_empty(json_path),
        )

        return CompileGenerateResponse(status="ok", files=generated_files)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to compile profile %s: %s", safe_name, exc)
        raise HTTPException(status_code=400, detail=str(exc))


@router.post(
    "/compile/deploy",
    summary="Deploy Staged Configuration",
    description="Deploy staged files from ready_for_deploy into active.",
    operation_id="compileDeployLegacy",
    response_model=CompileDeployResponse,
)
def compile_deploy() -> CompileDeployResponse:
    """Deploy staged artifacts to ACTIVE_DIR and return restart-required status."""
    try:
        compiler = HalCompiler(None)
        result = compiler.deploy_to_active()
        return CompileDeployResponse(status="ok", result=result)
    except Exception as exc:
        logger.error("Failed to deploy staged configuration: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to deploy staged configuration.")
