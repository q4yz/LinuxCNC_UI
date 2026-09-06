"""Shared paths for the domain file services."""
import json
from pathlib import Path
from typing import Optional

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
NC_FILES_DIR = _PROJECT_ROOT / "nc_files"
M_CODES_DIR = MACHINE_CONFIG_DIR / "m_codes"
MACROS_DIR = _PROJECT_ROOT / "macros"

#: Name of the persisted default-machine pointer file, sibling of
#: ``machines/`` (see ``system.services.MachineLifecycleService``,
#: which is the only writer — this module only ever reads it).
_DEFAULT_MACHINE_FILE_NAME = "default_machine.json"


def _read_default_machine_name(machine_config_dir: Path) -> Optional[str]:
    """Best-effort read of the persisted default machine's name.

    Pure filesystem read — no import of ``MachineLifecycleService``
    (which lives in the system app) so this stays callable from the
    machine backend without crossing the app boundary. Returns
    ``None`` on any error (missing file, malformed JSON, no machine
    selected yet); callers already treat "no hardware.json" as the
    graceful-empty case.
    """
    path = machine_config_dir / _DEFAULT_MACHINE_FILE_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    name = data.get("default_machine") if isinstance(data, dict) else None
    return name if isinstance(name, str) and name else None


def default_machine_hardware_json(repo_root: Optional[Path] = None) -> Path:
    """Resolve the persisted default machine's ``hardware.json``.

    ``machine_config/active/`` and ``machine_config/ready_for_deploy/``
    are gone — a machine's config lives directly under
    ``machine_config/machines/<name>/`` (``config/`` for a hand-laid
    out machine, ``configs/`` for the template generator's output;
    both are checked, first match wins, mirroring
    ``MachineLifecycleService.machine_ini``'s resolution).

    Returns a path even when no default machine is selected yet, or
    the file doesn't exist — every caller here already treats a
    missing ``hardware.json`` as the graceful "return empty" case
    rather than an error.
    """
    root = Path(repo_root) if repo_root is not None else PROJECT_ROOT
    machine_config_dir = root / "machine_config"
    machines_dir = machine_config_dir / "machines"

    name = _read_default_machine_name(machine_config_dir)
    if not name:
        return machines_dir / "__no_default_machine__" / "config" / "hardware.json"

    base = machines_dir / name
    for relative in ("config/hardware.json", "configs/hardware.json"):
        candidate = base / relative
        if candidate.is_file():
            return candidate
    return base / "config" / "hardware.json"
