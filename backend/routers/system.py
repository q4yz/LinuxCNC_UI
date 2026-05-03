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
