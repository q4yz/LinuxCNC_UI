"""Shared paths for the domain file services."""
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_PROJECT_ROOT = _BACKEND_ROOT.parent

#: Repository root — the single source of truth for any generator
#: that needs to emit an absolute, deployment-location-independent
#: path (e.g. the machine template generator's ``PROGRAM_PREFIX`` /
#: ``USER_M_PATH`` / ``[APPLICATIONS] APP`` INI values).
PROJECT_ROOT = _PROJECT_ROOT

MACHINE_CONFIG_DIR = _PROJECT_ROOT / "machine_config"
PROFILES_DIR = MACHINE_CONFIG_DIR / "profiles"
MACHINES_DIR = MACHINE_CONFIG_DIR / "machines"
STAGED_DIR = MACHINE_CONFIG_DIR / "ready_for_deploy"
ACTIVE_DIR = MACHINE_CONFIG_DIR / "active"
NC_FILES_DIR = _PROJECT_ROOT / "nc_files"
M_CODES_DIR = MACHINE_CONFIG_DIR / "m_codes"
MACROS_DIR = _PROJECT_ROOT / "macros"