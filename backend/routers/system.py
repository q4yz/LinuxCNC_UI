import logging
import subprocess
import time
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks

logger = logging.getLogger("backend.routers.system")

router = APIRouter(prefix="/api/v1/system", tags=["System"])


def _project_root() -> Path:
    """Return the repository root (three levels above this file: routers/ -> backend/ -> repo)."""
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


def _perform_update() -> None:
    """Simulate a time-consuming update task in the background."""
    logger.info("System update: starting simulated update task...")
    time.sleep(5)
    logger.info("System update: simulated update complete.")


@router.get(
    "/version",
    summary="Get Version Info",
    description="Return the current build version, latest known release, and whether an update is available.",
)
def get_version() -> dict:
    return {
        "version": _current_commit_hash(),
        "current_version": "v1.0.0",
        "latest_version": "v1.0.1",
        "update_available": True,
    }


@router.post(
    "/update",
    summary="Trigger System Update",
    description="Schedule a simulated system update to run after the response is returned.",
)
def trigger_update(background_tasks: BackgroundTasks) -> dict:
    background_tasks.add_task(_perform_update)
    return {"status": "update started"}
