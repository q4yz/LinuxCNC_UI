"""Saved bed meshes and the active one (`.agent/component/bed_mesh.md`).

A mesh is a file ``machine_config/bed_meshes/<name>.txt`` with one
``x y z`` line per probe point on a regular grid — the format
LinuxCNC's ``gridprobe.ngc`` writes and the Remora ``compensation``
component reads. Activating a mesh copies it to
``machine_config/bed_mesh_active.txt``, the fixed file
``machine.hal`` hands the component; its first line (a ``#`` comment
the component skips) names the mesh. The component reloads the file
the next time compensation is switched on.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

from core.bed_mesh_file import ACTIVE_HEADER, format_grid
from domain_file_services import paths
from exceptions import BadRequestError, ConflictError, NotFoundError
from models.BedMeshModels import BedMeshDefaults, BedMeshGrid, BedMeshListResponse

_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_ACTIVE_HEADER = ACTIVE_HEADER
#: The mesh a machine with ``[bed_mesh]`` starts with: flat, no offset.
FLAT_MESH = "flat"


class BedMeshService:
    def __init__(self, meshes_dir: Optional[Path] = None, active_file: Optional[Path] = None) -> None:
        self._dir = meshes_dir or paths.BED_MESHES_DIR
        self._active = active_file or paths.ACTIVE_BED_MESH_FILE

    # -- queries -------------------------------------------------------- #

    def list(self) -> BedMeshListResponse:
        names = sorted(p.stem for p in self._dir.glob("*.txt")) if self._dir.is_dir() else []
        return BedMeshListResponse(names=names, active=self.active_name())

    def active_name(self) -> Optional[str]:
        try:
            first = self._active.read_text(encoding="utf-8").splitlines()[0]
        except (OSError, IndexError):
            return None
        if not first.startswith(_ACTIVE_HEADER):
            return None
        return first[len(_ACTIVE_HEADER):].strip() or None

    def read(self, name: str) -> BedMeshGrid:
        path = self._path(name)
        if not path.is_file():
            raise NotFoundError(f"No bed mesh named {name!r}.")
        return self._parse(name, path.read_text(encoding="utf-8"))

    def defaults(self, hardware_json: Optional[Path] = None) -> BedMeshDefaults:
        """``probe_count`` over the X / Y limits of the default machine;
        the model defaults where it has none."""
        try:
            payload = json.loads((hardware_json or paths.default_machine_hardware_json()).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return BedMeshDefaults()
        return self.defaults_for(payload)

    @staticmethod
    def defaults_for(payload: dict[str, Any]) -> BedMeshDefaults:
        result = BedMeshDefaults()
        counts = (payload.get("bed_mesh") or {}).get("probe_count") or [3, 3]
        result.x_count, result.y_count = int(counts[0]), int(counts[1])
        for axis in payload.get("axes") or []:
            letter = str(axis.get("id", "")).lower()
            # position_min is Klipper's optional 0.
            low, high = axis.get("position_min") or 0.0, axis.get("position_max")
            if letter in ("x", "y") and high is not None:
                setattr(result, f"{letter}_min", float(low))
                setattr(result, f"{letter}_max", float(high))
        return result

    # -- commands ------------------------------------------------------- #

    def save(self, grid: BedMeshGrid) -> BedMeshGrid:
        self._check_grid(grid)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path(grid.name).write_text(self._format(grid), encoding="utf-8")
        if self.active_name() == grid.name:
            self.activate(grid.name)  # keep the component's copy current
        return grid

    def create(self, name: str, spec: BedMeshDefaults) -> BedMeshGrid:
        if self._path(name).exists():
            raise ConflictError(f"A bed mesh named {name!r} already exists.")
        if spec.x_count < 2 or spec.y_count < 2 or spec.x_min >= spec.x_max or spec.y_min >= spec.y_max:
            raise BadRequestError("A mesh needs at least 2 x 2 points and min < max on X and Y.")
        xs = [spec.x_min + i * (spec.x_max - spec.x_min) / (spec.x_count - 1) for i in range(spec.x_count)]
        ys = [spec.y_min + i * (spec.y_max - spec.y_min) / (spec.y_count - 1) for i in range(spec.y_count)]
        grid = BedMeshGrid(name=name, xs=xs, ys=ys, z=[[0.0] * len(xs) for _ in ys])
        return self.save(grid)

    def delete(self, name: str) -> None:
        path = self._path(name)
        if not path.is_file():
            raise NotFoundError(f"No bed mesh named {name!r}.")
        if self.active_name() == name:
            raise ConflictError(f"{name!r} is the active mesh — activate another one first.")
        path.unlink()

    def activate(self, name: str) -> BedMeshListResponse:
        grid = self.read(name)
        self._active.parent.mkdir(parents=True, exist_ok=True)
        self._active.write_text(_ACTIVE_HEADER + name + "\n" + self._format(grid), encoding="utf-8")
        return self.list()

    def ensure_active(self, payload: dict[str, Any]) -> None:
        """A machine with ``[bed_mesh]`` needs the active file before
        LinuxCNC starts the component: a flat mesh over its grid."""
        if self._active.is_file():
            return
        if not self._path(FLAT_MESH).is_file():
            self.create(FLAT_MESH, self.defaults_for(payload))
        self.activate(FLAT_MESH)

    # -- file format ---------------------------------------------------- #

    def _path(self, name: str) -> Path:
        if not _NAME.fullmatch(name or ""):
            raise BadRequestError(f"Invalid mesh name {name!r}: letters, digits, '_', '-', '.' only.")
        return self._dir / f"{name}.txt"

    @staticmethod
    def _format(grid: BedMeshGrid) -> str:
        return format_grid(grid.xs, grid.ys, grid.z)  # core.bed_mesh_file

    @staticmethod
    def _parse(name: str, text: str) -> BedMeshGrid:
        points: dict[tuple[float, float], float] = {}
        for line in text.splitlines():
            fields = line.split()
            if not fields or fields[0].startswith("#"):
                continue
            try:
                x, y, z = (float(v) for v in fields[:3])
            except ValueError:
                raise BadRequestError(f"Bed mesh {name!r}: bad line {line!r}.") from None
            points[(x, y)] = z
        xs = sorted({x for x, _ in points})
        ys = sorted({y for _, y in points})
        if len(points) != len(xs) * len(ys) or not points:
            raise BadRequestError(f"Bed mesh {name!r} is not a complete regular grid.")
        return BedMeshGrid(name=name, xs=xs, ys=ys, z=[[points[(x, y)] for x in xs] for y in ys])

    @staticmethod
    def _check_grid(grid: BedMeshGrid) -> None:
        if len(grid.xs) < 2 or len(grid.ys) < 2:
            raise BadRequestError("A mesh needs at least 2 x 2 points.")
        if grid.xs != sorted(set(grid.xs)) or grid.ys != sorted(set(grid.ys)):
            raise BadRequestError("Grid coordinates must be strictly ascending.")
        if len(grid.z) != len(grid.ys) or any(len(row) != len(grid.xs) for row in grid.z):
            raise BadRequestError("z needs one row per Y and one value per X.")


_service: Optional[BedMeshService] = None


def get_bed_mesh_service() -> BedMeshService:
    global _service
    if _service is None:
        _service = BedMeshService()
    return _service


__all__ = ["BedMeshService", "FLAT_MESH", "get_bed_mesh_service"]
