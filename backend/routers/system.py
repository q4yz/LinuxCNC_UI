import time
import threading
import logging
from fastapi import APIRouter, BackgroundTasks

logger = logging.getLogger("backend.routers.system")

router = APIRouter(prefix="/api/v1/system", tags=["System"])


def _perform_update():
    """Simulate a time-consuming update task."""
    logger.info("System update: starting simulated update task...")
    # Simulate work
    time.sleep(5)
    logger.info("System update: simulated update complete.")


@router.get('/version', summary='Get Version Info')
def get_version():
    # In a real system this would check the current package, VCS, or remote API
    # Provide both legacy `version` (commit/tag) and detailed fields
    return {
        "version": "496aec4",
        "current_version": "v1.0.0",
        "latest_version": "v1.0.1",
        "update_available": True
    }


@router.post('/update', summary='Trigger System Update')
def trigger_update(background_tasks: BackgroundTasks):
    # Schedule the simulated update to run after returning the response
    background_tasks.add_task(_perform_update)
    return {"status": "update started"}
import logging
import subprocess
import os
from fastapi import APIRouter, BackgroundTasks, HTTPException

logger = logging.getLogger("backend.routers.system")
router = APIRouter(prefix="/api/v1/system", tags=["System"])

def run_update_script():
    """Executes the update.sh script in the background."""
    script_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "scripts", "update.sh")
    try:
        # Use bash to run the script
        result = subprocess.run(["bash", script_path], capture_output=True, text=True)
        logger.info(f"Update script finished with code {result.returncode}")
        logger.info(f"Update script stdout: {result.stdout}")
        if result.stderr:
            logger.error(f"Update script stderr: {result.stderr}")
    except Exception as e:
        logger.error(f"Failed to run update script: {e}")

@router.get("/version", summary="Get System Version", description="Returns the current Git commit hash.")
def get_version():
    try:
        root_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], 
            cwd=root_dir,
            capture_output=True, 
            text=True, 
            check=True
        )
        return {"version": result.stdout.strip()}
    except Exception as e:
        logger.error(f"Failed to get git version: {e}")
        return {"version": "unknown"}

@router.post("/update", summary="Update System", description="Pulls the latest code and updates dependencies.")
def update_system(background_tasks: BackgroundTasks):
    logger.warning("System update initiated via API.")
    background_tasks.add_task(run_update_script)
    return {"status": "Update started"}
