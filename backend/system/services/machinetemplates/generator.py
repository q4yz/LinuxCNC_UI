"""Template generation orchestrator.

Generates the per-machine template set from a profile ``.cfg``:

    profiles/<path>.cfg  ->  machines/<target_folder>/<stem>/configs/
                               machine.cfg    (verbatim source copy)
                               hardware.json  (real, existing generator)
                               machine.ini    (template skeleton)
                               machine.hal    (template + pin catalog)

``config.txt`` (Remora flash payload) is intentionally NOT generated.

The machine name is the source file stem. When the target machine
folder already exists :class:`MachineExistsError` is raised unless
``confirm_override`` is set — the router translates that into a 409
the frontend confirms before retrying.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from machineconfig_parser import parse_config
from domain_file_services.ConfigFileService import ConfigFileService
from domain_file_services.MachineFileService import MachineFileService
from services.machineconfig.hardware_json_generator import build_hardware_json

from .hal_template_generator import render_hal_template
from .ini_template_generator import render_ini_template
from .pin_catalog import PinCatalog, build_pin_catalog

logger = logging.getLogger("backend.services.machinetemplates")

#: Basenames every generation writes into ``configs/``.
GENERATED_FILES = ("machine.cfg", "hardware.json", "machine.ini", "machine.hal")


class MachineExistsError(Exception):
    """Raised when the target machine folder already exists.

    Attributes:
        machine: The machine name (= source file stem).
        existing_files: Relative paths currently on disk under the
            machine folder.
    """

    def __init__(self, machine: str, existing_files: List[str]) -> None:
        self.machine = machine
        self.existing_files = existing_files
        super().__init__(
            f"Machine '{machine}' already exists "
            f"({len(existing_files)} file(s)); pass confirm_override to replace it."
        )


@dataclass(frozen=True)
class GenerateResult:
    """Outcome of one :func:`generate_machine_templates` run."""

    machine: str
    target_folder: str
    files: List[str] = field(default_factory=list)


def _normalize_target(target_folder: str) -> str:
    """Normalize the optional target folder to a clean relative prefix."""
    parts = [p for p in (target_folder or "").replace("\\", "/").split("/") if p]
    if any(p in {".", ".."} for p in parts):
        raise ValueError(f"Invalid target folder: {target_folder!r}")
    return "/".join(parts)


def _machine_configs_relpath(machine_name: str, target_folder: str) -> str:
    prefix = f"{target_folder}/" if target_folder else ""
    return f"{prefix}{machine_name}/configs"


def generate_machine_templates(
    profile_path: str,
    target_folder: str = "",
    confirm_override: bool = False,
    *,
    config_service: Optional[ConfigFileService] = None,
    machine_service: Optional[MachineFileService] = None,
    catalog: Optional[PinCatalog] = None,
) -> GenerateResult:
    """Generate the template set for ``profile_path``.

    Args:
        profile_path: Path relative to ``profiles/``.
        target_folder: Optional folder under ``machines/`` to nest the
            machine folder in (supports operator grouping).
        confirm_override: Replace an existing machine folder without
            the existence check.
        config_service: Override for tests (defaults to the factory).
        machine_service: Override for tests (defaults to the factory).
        catalog: Pre-built pin catalog override (defaults to the
            preloaded services).

    Raises:
        FileNotFoundError: The profile does not exist.
        ValueError: Path traversal or invalid target folder.
        MachineExistsError: Target exists and ``confirm_override`` is false.
    """
    config_service = config_service or ConfigFileService()
    machine_service = machine_service or MachineFileService()

    source = config_service.safe_join(profile_path)
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"Profile not found: {profile_path}")

    machine_name = source.stem
    target_folder = _normalize_target(target_folder)
    configs_rel = _machine_configs_relpath(machine_name, target_folder)
    configs_dir = machine_service.safe_join(configs_rel)

    if configs_dir.exists() and not confirm_override:
        existing = sorted(
            str(p.relative_to(machine_service.root)).replace("\\", "/")
            for p in configs_dir.rglob("*")
            if p.is_file()
        )
        raise MachineExistsError(machine_name, existing)

    # Parse + build the real hardware.json payload (unchanged generator).
    graph = parse_config(source)
    payload: Dict = build_hardware_json(graph, machine_name)

    if catalog is None:
        catalog = build_pin_catalog()

    machine_service.clear_directory(configs_dir)

    # 1. Verbatim source copy (provenance).
    (configs_dir / "machine.cfg").write_bytes(source.read_bytes())

    # 2. The real runtime contract.
    (configs_dir / "hardware.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )

    # 3. The ini skeleton.
    (configs_dir / "machine.ini").write_text(
        render_ini_template(machine_name, payload), encoding="utf-8"
    )

    # 4. The HAL pin catalog template.
    (configs_dir / "machine.hal").write_text(
        render_hal_template(machine_name, catalog), encoding="utf-8"
    )

    files = [
        f"{configs_rel}/{name}"
        for name in GENERATED_FILES
        if (configs_dir / name).exists()
    ]
    logger.info(
        "Generated machine templates for '%s' under %s", machine_name, configs_rel
    )
    return GenerateResult(
        machine=machine_name, target_folder=target_folder, files=files
    )


__all__ = [
    "GENERATED_FILES",
    "GenerateResult",
    "MachineExistsError",
    "generate_machine_templates",
]
