"""Bed mesh files (`.agent/component/bed_mesh.md` § 4), shared by the
system service (list / edit / activate) and the machine backend (writes a
probed mesh).

``bed_meshes/<name>.txt``: one ``x y z`` line per point on a regular
grid, row by row, X fastest — LinuxCNC's ``gridprobe.ngc`` order, single
spaces (the ``compensation`` component reads it with ``delimiter=" "``).
The active copy, ``bed_mesh_active.txt``, starts with ``# mesh: <name>``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

ACTIVE_HEADER = "# mesh: "


def format_grid(xs: Sequence[float], ys: Sequence[float], z: Sequence[Sequence[float]]) -> str:
    return "".join(
        f"{x:g} {y:g} {z[row][col]:.4f}\n" for row, y in enumerate(ys) for col, x in enumerate(xs)
    )


def write_mesh(
    name: str, xs: Sequence[float], ys: Sequence[float], z: Sequence[Sequence[float]],
    meshes_dir: Path, active_file: Path | None = None,
) -> Path:
    """Save ``bed_meshes/<name>.txt``; with ``active_file`` also make it
    the active mesh. Returns the mesh file."""
    text = format_grid(xs, ys, z)
    meshes_dir.mkdir(parents=True, exist_ok=True)
    path = meshes_dir / f"{name}.txt"
    path.write_text(text, encoding="utf-8")
    if active_file is not None:
        active_file.parent.mkdir(parents=True, exist_ok=True)
        active_file.write_text(ACTIVE_HEADER + name + "\n" + text, encoding="utf-8")
    return path


__all__ = ["ACTIVE_HEADER", "format_grid", "write_mesh"]
