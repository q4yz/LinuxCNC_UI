import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
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


def _launch_update_script() -> bool:
    """Detach scripts/update.sh from this Uvicorn process (git pull + pip install).

    The script stops and restarts linuxcnc-ui-system — the very service serving
    this request — so it must not run inside our session/process group and must
    not be awaited. A blocking run (or a BackgroundTask thread) deadlocks the
    shutdown until systemd's stop timeout SIGKILLs the whole cgroup, killing the
    script mid-update. start_new_session=True promotes it to its own process
    leader, and with KillMode=process in the unit file systemd signals only the
    main Uvicorn PID, so the script survives the restart. Output is appended to
    update.log in the repo root (same convention as rebuild_ui.sh).
    """
    script_path = _project_root() / "scripts" / "update.sh"
    if not script_path.exists():
        logger.error("Update script not found at %s", script_path)
        return False

    log_path = _project_root() / "update.log"
    popen_kwargs: dict[str, Any] = {}
    if sys.platform != "win32":
        popen_kwargs["start_new_session"] = True

    try:
        with log_path.open("ab") as log_file:
            subprocess.Popen(
                ["bash", str(script_path)],
                cwd=str(_project_root()),
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                **popen_kwargs,
            )
    except FileNotFoundError:
        logger.error("bash executable not found; cannot run update.sh")
        return False
    except Exception:  # noqa: BLE001
        logger.exception("Failed to launch update script")
        return False
    logger.info("Update script launched detached; output appending to %s", log_path)
    return True


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
    description="Launch scripts/update.sh (git pull + pip install) as a detached process so it survives the service restart it performs.",
    operation_id="triggerSystemUpdate",
    response_model=SystemUpdateResponse,
)
def trigger_update() -> SystemUpdateResponse:
    logger.warning("System update initiated via API.")
    if not _launch_update_script():
        raise HTTPException(status_code=500, detail="Failed to launch update script")
    return SystemUpdateResponse(status="update initiated; system is restarting")
