"""Klipper → LinuxCNC compiler.

The Klipper configuration (``.cfg``) is the absolute source of
truth. Operators author a Klipper config and this compiler derives
the backend's deployment artifacts from it.

Issue #41 wires the Klipper-to-LinuxCNC translation into the new
``machineconfig`` module's pluggable compiler framework. The compiler
reads a Klipper-style ``.cfg`` source file (the same shape the legacy
``HalCompiler`` consumed) and writes the canonical staged artifacts:

* ``machine.cfg`` — verbatim Klipper source so downstream tooling
  can resolve include paths identically to Klipper.
* ``linuxcnc.ini`` — LinuxCNC INI with safe defaults plus a sane
  ``[EMC]`` / ``[HAL]`` skeleton ready for hand-edit.
* ``machine.hal`` — stub HAL file; the translator is intentionally a
  starting point rather than a 1:1 conversion because Klipper's
  pin/scheduler vocabulary has no direct LinuxCNC equivalent.
* ``hardware.json`` — the backend's internal hardware knowledge,
  derived from the Klipper source (formerly ``remora.json``).
* ``config.txt`` — the payload written to the Remora board.

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
from .axis_builder import AxisBuilder
from .base import Compiler
from .config_txt_generator import write_config_txt
from .hal_generator import HalGenerator, build_hal_from_graph
from .hardware_json_generator import write_hardware_json
from .ini_generator import IniGenerator, build_ini_from_graph

logger = logging.getLogger("backend.modules.machineconfig.compilers.klipper_linuxcnc")


class KlipperToLinuxCNCCompiler(Compiler):
    """Default Klipper → LinuxCNC translator.

    The class is a faithful port of :class:`backend.services.hal_compiler.HalCompiler`'s
    output layout, re-shaped to fit the new :class:`Compiler` contract:

    * The five emitted files (``machine.cfg``, ``linuxcnc.ini``,
      ``machine.hal``, ``hardware.json``, ``config.txt``) share the
      same basenames so operators looking for them by hand don't
      need to relearn anything.
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
        "hardware.json",
        "config.txt",
    )

    def compile(self, source_path: Path, output_dir: Path) -> List[Path]:
        """Stage the Klipper source + generated artifacts under ``output_dir``.

        The router already wipes ``output_dir`` before calling us, so we
        only need to write the five canonical artifacts.
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
        self._write_ini(output_dir / "linuxcnc.ini", machine)
        self._write_hal(output_dir / "machine.hal", machine)
        self._write_hardware_json(output_dir / "hardware.json", machine, machine_name)
        self._write_config_txt(output_dir / "config.txt", machine, machine_name)

        logger.info(
            "KlipperToLinuxCNCCompiler staged %s → %s", source_path, output_dir
        )
        return [output_dir / name for name in self.ARTIFACT_NAMES]

    # ------------------------------------------------------------------ #
    # Artifact generators                                                #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _write_ini(path: Path, machine) -> None:
        """Render the LinuxCNC ``.ini`` from the parsed Klipper graph.

        The static template lives in :mod:`.ini_generator`; this
        method is the glue that builds an :class:`IniConfig` from
        the parsed graph and runs it through
        :class:`IniGenerator`. The full template honors the
        Axis-to-Joint mapping rules implemented by
        :class:`~.axis_builder.AxisBuilder` so multi-motor
        configurations render correctly without code changes here.
        """
        ini_config = build_ini_from_graph(machine)
        rendered = IniGenerator().render(ini_config)
        path.write_text(rendered, encoding="utf-8")

    @staticmethod
    def _write_hal(path: Path, machine) -> None:
        """Render the LinuxCNC ``.hal`` from the parsed Klipper graph.

        The static template lives in :mod:`.hal_generator`; this
        method is the glue that builds an :class:`IniConfig` from
        the parsed graph and runs it through :class:`HalGenerator`.
        The full template honors the Axis-to-Joint mapping rules
        implemented by :class:`~.axis_builder.AxisBuilder` so
        multi-motor configurations render correctly without code
        changes here.
        """
        rendered = build_hal_from_graph(machine)
        path.write_text(rendered, encoding="utf-8")

    @staticmethod
    def _write_hardware_json(
        path: Path,
        machine,
        machine_name: str,
    ) -> None:
        """Write the backend's internal hardware knowledge JSON.

        ``hardware.json`` is the canonical record of every pin, stepper,
        heater, and fan the backend knows about. It is derived from the
        parsed Klipper graph at compile time and consumed by everything
        that needs to query the hardware (deployment tools, the console,
        future Remora firmware flasher) without parsing the raw config
        again.
        """
        write_hardware_json(path, machine, machine_name)

    @staticmethod
    def _write_config_txt(
        path: Path,
        machine,
        machine_name: str,
    ) -> None:
        """Write the Remora board payload (``config.txt``).

        This is the file that gets flashed to the Remora board. It
        contains a ``Modules`` array with Stepgen, TMC2209, Digital
        Pin, Temperature, and PWM modules populated dynamically from
        the parsed Klipper graph.
        """
        write_config_txt(path, machine, machine_name)