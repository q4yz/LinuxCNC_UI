import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from models.UpdateModels import SystemUpdateRequest, SystemUpdateResponse, UpdateStatusResponse
from services.UpdateService import UpdateLaunchError, get_update_service
from services.VersionService import get_version_service

logger = logging.getLogger("backend.routers.system")

router = APIRouter(prefix="/api/v1/system", tags=["System"])


class VersionInfoResponse(BaseModel):
    """Response model for GET /system/version."""
    version: str = Field(..., description="Short git commit hash identifying the running build")
    current_version: str = Field(..., description="Running version (git describe: release tag, or tag-N-gHASH on a commit build)")
    latest_version: Optional[str] = Field(default=None, description="Tag of the latest GitHub release; null when none exists or GitHub is unreachable")
    update_available: bool = Field(..., description="Whether the latest release is newer than the release this build is on / based on")


@router.get(
    "/version",
    summary="Get Version Info",
    description="Return the current build version, latest known release, and whether an update is available.",
    operation_id="getVersionInfo",
    response_model=VersionInfoResponse,
)
def get_version() -> VersionInfoResponse:
    versions = get_version_service()
    latest = versions.latest_release()
    return VersionInfoResponse(
        version=versions.commit(),
        current_version=versions.describe(),
        latest_version=latest,
        update_available=versions.release_available(latest),
    )


@router.post(
    "/update",
    summary="Trigger System Update",
    description=(
        "Launch scripts/update.sh as a detached process so it survives the service restart "
        "it performs. mode=commit: git pull + UI build on the board (testing). "
        "mode=release: check out the latest GitHub release and install its prebuilt UI "
        "(no npm on the board). "
        "Follow it with GET /update/status and the returned run_id. 409 while an update runs."
    ),
    operation_id="triggerSystemUpdate",
    response_model=SystemUpdateResponse,
    responses={409: {"description": "An update is already running."}},
)
def trigger_update(request: Optional[SystemUpdateRequest] = None) -> SystemUpdateResponse:
    mode = request.mode if request else "commit"
    logger.warning("System update (%s) initiated via API.", mode)
    try:
        run_id = get_update_service().start(mode)
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
