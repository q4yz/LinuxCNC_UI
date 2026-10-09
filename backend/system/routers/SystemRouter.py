import logging
import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from models.UpdateModels import SystemUpdateResponse, UpdateStatusResponse
from services.UpdateService import UpdateLaunchError, get_update_service

logger = logging.getLogger("backend.routers.system")

router = APIRouter(prefix="/api/v1/system", tags=["System"])


class VersionInfoResponse(BaseModel):
    """Response model for GET /system/version."""
    version: str = Field(..., description="Short git commit hash identifying the running build")
    current_version: str = Field(..., description="Human-readable current release tag")
    latest_version: str = Field(..., description="Human-readable latest known release tag")
    update_available: bool = Field(..., description="Whether a newer release is known to be available")


def _project_root() -> Path:
    """Return the repository root (three levels above this file: routers/ -> system/ -> backend/ -> repo)."""
    return Path(__file__).resolve().parents[3]


def _current_commit_hash() -> str:
    """Return the short git commit hash for the repo, or 'unknown' if it cannot be determined."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(_project_root()),
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return result.stdout.strip() or "unknown"
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        logger.warning("Unable to determine git commit hash: %s", exc)
        return "unknown"


@router.get(
    "/version",
    summary="Get Version Info",
    description="Return the current build version, latest known release, and whether an update is available.",
    operation_id="getVersionInfo",
    response_model=VersionInfoResponse,
)
def get_version() -> VersionInfoResponse:
    return VersionInfoResponse(
        version=_current_commit_hash(),
        current_version="v1.0.0",
        latest_version="v1.0.1",
        update_available=True,
    )


@router.post(
    "/update",
    summary="Trigger System Update",
    description=(
        "Launch scripts/update.sh (git pull, dependencies, UI rebuild, service restart) "
        "as a detached process so it survives the service restart it performs. "
        "Follow it with GET /update/status and the returned run_id. 409 while an update runs."
    ),
    operation_id="triggerSystemUpdate",
    response_model=SystemUpdateResponse,
    responses={409: {"description": "An update is already running."}},
)
def trigger_update() -> SystemUpdateResponse:
    logger.warning("System update initiated via API.")
    try:
        run_id = get_update_service().start()
    except UpdateLaunchError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to launch update script: {exc}") from exc
    return SystemUpdateResponse(status="update initiated; system is restarting", run_id=run_id)


@router.get(
    "/update/status",
    summary="Get System Update Status",
    description=(
        "Progress of the last update, written by scripts/update.sh. 'done' is written only "
        "after the restarted services answered, so the UI may reload on it."
    ),
    operation_id="getSystemUpdateStatus",
    response_model=UpdateStatusResponse,
)
def get_update_status() -> UpdateStatusResponse:
    return get_update_service().status()
