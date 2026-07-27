"""Klipper → LinuxCNC compiler.

Issue #41 wires the Klipper-to-LinuxCNC translation into the new
``machineconfig`` module's pluggable compiler framework. The compiler
reads a Klipper-style ``.cfg`` source file (the same shape the legacy
``HalCompiler`` consumed) and writes the canonical staged artifacts:

* ``machine.cfg`` — verbatim copy of the source so downstream tooling
  can resolve include paths the same way it would in Klipper.
* ``linuxcnc.ini`` — LinuxCNC INI with safe defaults plus a sane
  ``[EMC]`` / ``[HAL]`` skeleton ready for hand-edit.
* ``machine.hal`` — stub HAL file; the translator is intentionally a
  starting point rather than a 1:1 conversion because Klipper's
  pin/scheduler vocabulary has no direct LinuxCNC equivalent.
* ``remora.json`` — minimal Remora board payload used by the
  remote-controller flash flow.

The previous implementation lives at
``backend/services/hal_compiler.py`` and continues to back the legacy
``/api/v1/compiler/*`` endpoints. This module is the cleaner,
extensible replacement used by the new ``machineconfig`` module.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List

from ..parser import parse_config
from .base import Compiler

logger = logging.getLogger("backend.modules.machineconfig.compilers.klipper_linuxcnc")


class KlipperToLinuxCNCCompiler(Compiler):
    """Default Klipper → LinuxCNC translator.

    The class is a faithful port of :class:`backend.services.hal_compiler.HalCompiler`'s
    output layout, re-shaped to fit the new :class:`Compiler` contract:

    * The four emitted files (``machine.cfg``, ``linuxcnc.ini``,
      ``machine.hal``, ``remora.json``) share the same basenames so
      operators looking for them by hand don't need to relearn anything.
    * The source marker default is :data:`DEFAULT_SOURCE_MARKER`
      (``#Start``), matching the issue brief.
    * The compiler enforces the strict Klipper schema before writing
      artifacts, so unsupported sections and keywords fail fast.
    """

    id = "klipper-to-linuxcnc"
    title = "Klipper → LinuxCNC"
    source_marker = "#Start"

    #: Files emitted by :meth:`compile`. Kept as a class attribute so the
    #: router can pre-declare them in OpenAPI without an instance.
    ARTIFACT_NAMES: tuple[str, ...] = (
        "machine.cfg",
        "linuxcnc.ini",
        "machine.hal",
        "remora.json",
    )

    def compile(self, source_path: Path, output_dir: Path) -> List[Path]:
        """Stage the Klipper source + generated artifacts under ``output_dir``.

        The router already wipes ``output_dir`` before calling us, so we
        only need to write the four canonical artifacts.
        """
        if not source_path.exists() or not source_path.is_file():
            raise FileNotFoundError(f"Source profile not found: {source_path}")

        # 1. Parse and strictly validate the source before writing any
        # artifacts. The graph is retained so artifact writers can consume
        # linked components as the compiler grows.
        machine_name = source_path.stem
        machine = parse_config(source_path)
        printer_section = {}
        if machine.printer is not None:
            printer_section = {
                "kinematics": machine.printer.kinematics,
                "max_velocity": str(
                    machine.printer.max_velocity
                    if machine.printer.max_velocity is not None
                    else 300.0
                ),
                "max_accel": str(
                    machine.printer.max_accel
                    if machine.printer.max_accel is not None
                    else 3000.0
                ),
            }

        output_dir.mkdir(parents=True, exist_ok=True)

        # 2. Copy the source verbatim. Operators reading the staged folder by
        # hand expect ``machine.cfg`` to be the same file they edited.
        staged_source = output_dir / "machine.cfg"
        staged_source.write_bytes(source_path.read_bytes())

        # 3. Emit the generated artifacts.
        self._write_ini(output_dir / "linuxcnc.ini", machine_name, printer_section)
        self._write_hal(output_dir / "machine.hal", machine_name)
        self._write_remora_json(output_dir / "remora.json", machine_name, printer_section)

        logger.info(
            "KlipperToLinuxCNCCompiler staged %s → %s", source_path, output_dir
        )
        return [output_dir / name for name in self.ARTIFACT_NAMES]

    # ------------------------------------------------------------------ #
    # Artifact generators                                                #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _write_ini(path: Path, machine_name: str, printer_section: dict[str, str]) -> None:
        """Write a minimal but valid ``linuxcnc.ini``."""
        kinematics = printer_section.get("kinematics", "cartesian")
        max_velocity = printer_section.get("max_velocity", "300.0")
        max_accel = printer_section.get("max_accel", "3000.0")

        content = (
            f"# Generated by KlipperToLinuxCNCCompiler for '{machine_name}'\n"
            "[EMC]\n"
            "MACHINE = linuxcnc\n"
            "DEBUG = 0\n"
            "\n"
            "[DISPLAY]\n"
            "DISPLAY = axis\n"
            "PROGRAM_PREFIX = .\n"
            "\n"
            f"[KINS]\n"
            f"JOINTS = 3\n"
            f"KINEMATICS = {kinematics}\n"
            "\n"
            "[TRAJ]\n"
            f"MAX_VELOCITY = {max_velocity}\n"
            f"MAX_ACCELERATION = {max_accel}\n"
            "\n"
            "[HAL]\n"
            "HALFILE = machine.hal\n"
            "POSTGUI_HALFILE = postgui.hal\n"
        )
        path.write_text(content, encoding="utf-8")

    @staticmethod
    def _write_hal(path: Path, machine_name: str) -> None:
        """Write a stub HAL file with the right loadrt skeleton."""
        content = (
            f"# Generated by KlipperToLinuxCNCCompiler for '{machine_name}'\n"
            "# This is a starting point; replace the loadrt / setp lines\n"
            "# with the net list that matches your stepper wiring.\n"
            "loadrt [KINS]KINEMATICS\n"
            "loadrt thread_period1=[EMCMOT]BASE_PERIOD\n"
        )
        path.write_text(content, encoding="utf-8")

    @staticmethod
    def _write_remora_json(
        path: Path,
        machine_name: str,
        printer_section: dict[str, str],
    ) -> None:
        """Write the Remora board payload JSON."""
        payload = {
            "generated": True,
            "machine": machine_name,
            "source": "KlipperToLinuxCNCCompiler",
            "kinematics": printer_section.get("kinematics", "cartesian"),
            "steppers": [],
            "heaters": [],
            "note": "Populate steppers/heaters from the Klipper source as needed.",
        }
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


__all__ = ["KlipperToLinuxCNCCompiler"]