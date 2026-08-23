import logging
import subprocess
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel, Field

logger = logging.getLogger("backend.routers.system")

router = APIRouter(prefix="/api/v1/system", tags=["System"])


class VersionInfoResponse(BaseModel):
    """Response model for GET /system/version."""
    version: str = Field(..., description="Short git commit hash identifying the running build")
    current_version: str = Field(..., description="Human-readable current release tag")
    latest_version: str = Field(..., description="Human-readable latest known release tag")
    update_available: bool = Field(..., description="Whether a newer release is known to be available")


class SystemUpdateResponse(BaseModel):
    """Response model for POST /system/update."""
    status: str = Field(..., description="Outcome summary describing the update state")


def _project_root() -> Path:
    """Return the repository root (two levels above this file: routers/ -> backend/ -> repo)."""
    return Path(__file__).resolve().parents[2]


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


def _run_update_script() -> None:
    """Execute scripts/update.sh in the background (git pull + pip install).

    This is the real update routine — it was previously replaced by a placeholder
    that merely slept. The frontend expects this to perform an actual update.
    """
    script_path = _project_root() / "scripts" / "update.sh"
    if not script_path.exists():
        logger.error("Update script not found at %s", script_path)
        return

    try:
        result = subprocess.run(
            ["bash", str(script_path)],
            cwd=str(_project_root()),
            capture_output=True,
            text=True,
        )
        logger.info("Update script finished with code %s", result.returncode)
        if result.stdout:
            logger.info("Update script stdout:\n%s", result.stdout)
        if result.stderr:
            logger.error("Update script stderr:\n%s", result.stderr)
    except FileNotFoundError:
        logger.error("bash executable not found; cannot run update.sh")
    except Exception:  # noqa: BLE001
        logger.exception("Failed to run update script")


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
    description="Schedule scripts/update.sh (git pull + pip install) to run after the response is returned.",
    operation_id="triggerSystemUpdate",
    response_model=SystemUpdateResponse,
)
def trigger_update(background_tasks: BackgroundTasks) -> SystemUpdateResponse:
    logger.warning("System update initiated via API.")
    background_tasks.add_task(_run_update_script)
    return SystemUpdateResponse(status="update started")
