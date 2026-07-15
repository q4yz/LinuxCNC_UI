import logging
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.config_manager import MachineConfig
from services.hal_compiler import HalCompiler

logger = logging.getLogger("backend.routers.compiler")
router = APIRouter(prefix="/api/v1/compiler", tags=["Compiler"])

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MACHINE_CONFIG_DIR = PROJECT_ROOT / "machine_config"
PROFILES_DIR = MACHINE_CONFIG_DIR / "profiles"
READY_DIR = MACHINE_CONFIG_DIR / "ready_for_deploy"


def _list_profile_files() -> list[str]:
    """Return available .cfg profiles from profiles/ or machine_config/ root fallback."""
    source_dir = PROFILES_DIR if PROFILES_DIR.exists() else MACHINE_CONFIG_DIR
    excluded_dirs = {"active", "ready_for_deploy", "profiles", "__pycache__"}

    profiles = []
    for item in source_dir.iterdir():
        if item.is_dir() and source_dir == MACHINE_CONFIG_DIR and item.name in excluded_dirs:
            continue
        if item.is_file() and item.suffix.lower() == ".cfg":
            profiles.append(item.name)

    profiles.sort()
    return profiles


class CompilerProfilesResponse(BaseModel):
    """Response model for GET /compiler/profiles."""
    status: str = Field(..., description="Outcome summary (e.g., 'ok')")
    profiles: List[str] = Field(default_factory=list, description="List of available profile filenames")


class CompilerGeneratePreview(BaseModel):
    """Previews of staged compiler artifacts."""
    ini: str = Field(default="", description="Generated linuxcnc.ini preview")
    hal: str = Field(default="", description="Generated machine.hal preview")
    json: str = Field(default="", description="Generated remora.json preview")


class CompilerGenerateResponse(BaseModel):
    """Response model for POST /compiler/generate/{profile_name}."""
    status: str = Field(..., description="Outcome summary (e.g., 'ok')")
    message: str = Field(..., description="Human-readable generation summary")
    profile: str = Field(..., description="Resolved profile filename that was generated")
    generated_files: CompilerGeneratePreview = Field(..., description="Preview text of each generated artifact")
    staged: Dict[str, Any] = Field(default_factory=dict, description="Detailed compiler staging result")


class CompilerDeployResponse(BaseModel):
    """Response model for POST /compiler/deploy."""
    status: str = Field(..., description="Outcome summary (e.g., 'ok')")
    message: str = Field(..., description="Human-readable deployment summary")
    restart_required: bool = Field(..., description="Whether the LinuxCNC backend must be restarted for the new configuration to take effect")
    deployment: Dict[str, Any] = Field(default_factory=dict, description="Detailed compiler deployment result")


@router.get(
    "/profiles",
    summary="List compiler profiles",
    description="List all available configuration profiles that can be compiled into LinuxCNC artifacts.",
    operation_id="listCompilerProfiles",
    response_model=CompilerProfilesResponse,
)
def get_profiles() -> CompilerProfilesResponse:
    """List available configuration profiles for compilation."""
    try:
        return CompilerProfilesResponse(status="ok", profiles=_list_profile_files())
    except Exception as exc:
        logger.error("Failed to list compiler profiles: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to list compiler profiles.")


@router.post(
    "/generate/{profile_name}",
    summary="Generate staged compiler files",
    description="Compile the named profile into LinuxCNC artifacts staged under machine_config/ready_for_deploy.",
    operation_id="generateCompilerArtifacts",
    response_model=CompilerGenerateResponse,
)
def generate_staged(profile_name: str) -> CompilerGenerateResponse:
    """Generate staged machine.cfg + compiler artifacts and return file previews."""
    try:
        selected = profile_name if profile_name.endswith(".cfg") else f"{profile_name}.cfg"
        source_dir = PROFILES_DIR if PROFILES_DIR.exists() else MACHINE_CONFIG_DIR
        profile_path = source_dir / selected

        if not profile_path.exists() or not profile_path.is_file():
            raise HTTPException(status_code=404, detail=f"Profile not found: {selected}")

        config = MachineConfig(config_path=str(profile_path))
        compiler = HalCompiler(config)
        stage_result = compiler.generate_staged(selected)

        generated_ini = READY_DIR / "linuxcnc.ini"
        generated_hal = READY_DIR / "machine.hal"
        generated_json = READY_DIR / "remora.json"

        previews = CompilerGeneratePreview(
            ini=generated_ini.read_text(encoding="utf-8") if generated_ini.exists() else "",
            hal=generated_hal.read_text(encoding="utf-8") if generated_hal.exists() else "",
            json=generated_json.read_text(encoding="utf-8") if generated_json.exists() else "",
        )

        return CompilerGenerateResponse(
            status="ok",
            message=stage_result.get("message", "Generation complete."),
            profile=selected,
            generated_files=previews,
            staged=stage_result,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to generate staged compiler artifacts for %s: %s", profile_name, exc)
        raise HTTPException(status_code=500, detail="Failed to generate staged compiler artifacts.")


@router.post(
    "/deploy",
    summary="Deploy staged compiler files",
    description="Promote the staged artifacts in machine_config/ready_for_deploy into machine_config/active and mark the system restart-required.",
    operation_id="deployCompilerArtifacts",
    response_model=CompilerDeployResponse,
)
def deploy_staged() -> CompilerDeployResponse:
    """Deploy ready_for_deploy artifacts into active and mark restart-required."""
    try:
        compiler = HalCompiler(None)
        result = compiler.deploy_to_active()
        return CompilerDeployResponse(
            status="ok",
            message=result.get("message", "Deployment complete."),
            restart_required=True,
            deployment=result,
        )
    except Exception as exc:
        logger.error("Failed to deploy compiler artifacts: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to deploy compiler artifacts.")
