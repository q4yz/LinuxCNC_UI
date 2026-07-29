import json
import logging
import os
import shutil
from pathlib import Path
from typing import Iterable, List

from core.config_manager import MachineConfig

logger = logging.getLogger("backend.services.hal_compiler")


class HalCompiler:
    """Compiles staged LinuxCNC artifacts from an in-memory MachineConfig."""

    def __init__(self, config: MachineConfig):
        self.config = config

        project_root = Path(__file__).resolve().parents[2]
        self.machine_config_dir = project_root / "machine_config"
        self.profiles_dir = self.machine_config_dir / "profiles"
        self.ready_dir = self.machine_config_dir / "ready_for_deploy"
        self.active_dir = self.machine_config_dir / "active"

    def generate_staged(self, profile_name: str):
        """
        Prepare machine_config/ready_for_deploy from a source profile and generator outputs.

        - Clears ready_for_deploy/
        - Copies <profile_name>.cfg as machine.cfg
        - Copies tracked include .cfg files (if exposed by MachineConfig)
        - Generates derived files (INI, HAL, Remora JSON)
        """
        profile_file = self._resolve_profile_file(profile_name)

        self._clear_directory(self.ready_dir)

        staged_main = self.ready_dir / "machine.cfg"
        shutil.copy2(profile_file, staged_main)

        copied_includes = []
        for include_path in self._get_tracked_include_files(profile_file):
            include_name = include_path.name
            destination = self.ready_dir / include_name

            # Avoid overwriting staged main file if an include is also named machine.cfg.
            if destination.name == "machine.cfg":
                destination = self.ready_dir / f"include_{include_name}"

            shutil.copy2(include_path, destination)
            copied_includes.append(str(destination))

        self._generate_ini(str(self.ready_dir / "linuxcnc.ini"))
        self._generate_hal(str(self.ready_dir / "machine.hal"))
        self._generate_remora_json(str(self.ready_dir / "remora.json"))

        return {
            "status": "ok",
            "message": f"Staged profile '{profile_name}' for deployment.",
            "profile": profile_name,
            "staged_main": str(staged_main),
            "included_files": copied_includes,
        }

    def deploy_to_active(self):
        """
        Deploy ready_for_deploy artifacts into machine_config/active.

        Returns a restart-required marker so callers can notify operators.
        """
        if not self.ready_dir.exists():
            raise FileNotFoundError("Staging directory does not exist. Generate staged files first.")

        self._clear_directory(self.active_dir)

        for item in self.ready_dir.iterdir():
            target = self.active_dir / item.name
            if item.is_dir():
                shutil.copytree(item, target)
            else:
                shutil.copy2(item, target)

        return {
            "status": "ok",
            "message": "Deployment complete. LinuxCNC restart required.",
            "restart_required": True,
            "active_path": str(self.active_dir),
        }

    def _generate_ini(self, output_path: str):
        """Generate LinuxCNC INI file from self.config (stub for now)."""
        with open(output_path, "w", encoding="utf-8") as ini_file:
            # TODO: Build real INI content from self.config machine limits and sections.
            ini_file.write("# Generated INI for LinuxCNC\n")

    def _generate_hal(self, output_path: str):
        """Generate LinuxCNC HAL file from self.config (stub for now)."""
        with open(output_path, "w", encoding="utf-8") as hal_file:
            # TODO: Translate self.config stepper/pin mappings to HAL net/loadrt/setp lines.
            hal_file.write("# Generated HAL for LinuxCNC\n")

    def _generate_remora_json(self, output_path: str):
        """Generate ``hardware.json`` from ``self.config`` (stub for now).

        The legacy ``remora.json`` filename has been retired in favour
        of ``hardware.json`` (the backend's canonical hardware record).
        This method keeps its old name so the existing call sites in
        :meth:`generate_staged` keep working until the legacy
        ``/api/v1/compiler/*`` endpoints are migrated to the new
        ``machineconfig`` module.
        """
        payload = {
            "generated": True,
            "source": "HalCompiler",
            "note": "TODO: Populate with real pin/stepper payload from MachineConfig.",
            "steppers": [],
            "heaters": [],
        }
        with open(output_path, "w", encoding="utf-8") as remora_file:
            json.dump(payload, remora_file, indent=2)
            remora_file.write("\n")

    def _resolve_profile_file(self, profile_name: str) -> Path:
        sanitized_name = profile_name.strip()
        if not sanitized_name:
            raise ValueError("profile_name is required")

        if not sanitized_name.endswith(".cfg"):
            sanitized_name = f"{sanitized_name}.cfg"

        candidate = (self.profiles_dir / sanitized_name).resolve()
        profiles_root = self.profiles_dir.resolve()

        if profiles_root not in candidate.parents and candidate != profiles_root:
            raise ValueError(f"Invalid profile path: {profile_name}")

        if not candidate.exists() or not candidate.is_file():
            raise FileNotFoundError(f"Profile not found: {candidate}")

        return candidate

    def _get_tracked_include_files(self, profile_file: Path) -> List[Path]:
        """
        Resolve include files tracked by MachineConfig when available.

        MachineConfig remains a reader and may expose include tracking via attributes.
        This compiler consumes that tracking if present; otherwise it stages only the
        selected profile file.
        """
        include_candidates: List[Path] = []
        project_root = Path(__file__).resolve().parents[2]

        for attr_name in ("included_files", "include_files", "resolved_includes", "config_files"):
            raw_value = getattr(self.config, attr_name, None)
            if not raw_value:
                continue

            include_candidates.extend(self._normalize_paths(raw_value, project_root))

        # Never include the staged main profile again as a side include.
        deduped: List[Path] = []
        seen = set()
        for item in include_candidates:
            resolved = item.resolve()
            if resolved == profile_file.resolve():
                continue
            if resolved in seen:
                continue
            if not resolved.exists() or not resolved.is_file():
                logger.warning("Skipping tracked include that does not exist: %s", resolved)
                continue
            seen.add(resolved)
            deduped.append(resolved)

        return deduped

    def _normalize_paths(self, values: Iterable, project_root: Path) -> List[Path]:
        paths: List[Path] = []
        for value in values:
            p = Path(value)
            if not p.is_absolute():
                p = (project_root / p)
            paths.append(p)
        return paths

    def _clear_directory(self, directory: Path):
        if directory.exists():
            shutil.rmtree(directory)
        os.makedirs(directory, exist_ok=True)
