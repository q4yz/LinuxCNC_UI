"""Z tilt math (`.agent/component/z_tilt.md`), shared by the system
backend (the ``.cfg`` checks) and the machine backend (the adjustment).

Probed heights ``z`` at points ``(x, y)`` are fit by a plane
``z = a*x + b*y + c`` (least squares). Each Z motor's correction is the
plane's height at its pivot minus the mean of those heights: the motor
under a high corner moves up by as much as the bed is high there, and
the mean Z stays where it was.

Sign: the corrections are added to each motor's joint position (the
HAL ``offset`` component in front of it). A probe that triggers *higher*
at a corner means the gap is smaller there; raising that motor's joint
position (machine Z+ is "away from the bed" whichever part moves)
opens the gap by the same amount. So ``+(height - mean)`` is the move.
"""
from __future__ import annotations

from typing import Sequence

Point = tuple[float, float]

#: Below this, three points are taken as being on one line.
_COLLINEAR_EPS = 1e-6


def _area2(a: Point, b: Point, c: Point) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def collinear(points: Sequence[Point]) -> bool:
    """All points on one line (two points always are)."""
    if len(points) < 3:
        return True
    first = points[0]
    far = max(points, key=lambda p: (p[0] - first[0]) ** 2 + (p[1] - first[1]) ** 2)
    scale = max(1.0, (far[0] - first[0]) ** 2 + (far[1] - first[1]) ** 2)
    return all(abs(_area2(first, far, p)) / scale < _COLLINEAR_EPS for p in points)


def _solve3(m: list[list[float]], v: list[float]) -> list[float] | None:
    """Gaussian elimination with partial pivoting; ``None`` if singular."""
    a = [row[:] + [v[i]] for i, row in enumerate(m)]
    for col in range(3):
        pivot = max(range(col, 3), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-12:
            return None
        a[col], a[pivot] = a[pivot], a[col]
        for r in range(3):
            if r != col:
                f = a[r][col] / a[col][col]
                for k in range(col, 4):
                    a[r][k] -= f * a[col][k]
    return [a[i][3] / a[i][i] for i in range(3)]


def fit_heights(points: Sequence[Point], heights: Sequence[float], at: Sequence[Point]) -> list[float]:
    """The fitted surface's height at each point of ``at``.

    A plane through the probed points; when they are on one line (e.g.
    two motors, probed along the line between them) a straight line along
    that direction instead — the motors' pivots are projected onto it.
    """
    if len(points) != len(heights) or len(points) < 2:
        raise ValueError("need at least two probe points, one height each")
    n = float(len(points))
    if not collinear(points):
        sx = sum(p[0] for p in points)
        sy = sum(p[1] for p in points)
        sxx = sum(p[0] * p[0] for p in points)
        syy = sum(p[1] * p[1] for p in points)
        sxy = sum(p[0] * p[1] for p in points)
        sz = sum(heights)
        sxz = sum(p[0] * z for p, z in zip(points, heights))
        syz = sum(p[1] * z for p, z in zip(points, heights))
        coeffs = _solve3([[sxx, sxy, sx], [sxy, syy, sy], [sx, sy, n]], [sxz, syz, sz])
        if coeffs is not None:
            a, b, c = coeffs
            return [a * x + b * y + c for x, y in at]
    # One line: z = k*t + m with t the position along it.
    first = points[0]
    far = max(points, key=lambda p: (p[0] - first[0]) ** 2 + (p[1] - first[1]) ** 2)
    dx, dy = far[0] - first[0], far[1] - first[1]
    length = (dx * dx + dy * dy) ** 0.5
    if length == 0:
        mean = sum(heights) / n
        return [mean for _ in at]
    ux, uy = dx / length, dy / length
    ts = [(p[0] - first[0]) * ux + (p[1] - first[1]) * uy for p in points]
    mt, mz = sum(ts) / n, sum(heights) / n
    var = sum((t - mt) ** 2 for t in ts)
    k = sum((t - mt) * (z - mz) for t, z in zip(ts, heights)) / var if var else 0.0
    return [mz + k * (((x - first[0]) * ux + (y - first[1]) * uy) - mt) for x, y in at]


def motor_adjustments(
    points: Sequence[Point], heights: Sequence[float], z_positions: Sequence[Point]
) -> list[float]:
    """Each motor's correction (mm, added to its joint position), mean 0."""
    at_motors = fit_heights(points, heights, z_positions)
    mean = sum(at_motors) / len(at_motors)
    return [h - mean for h in at_motors]


__all__ = ["collinear", "fit_heights", "motor_adjustments"]
