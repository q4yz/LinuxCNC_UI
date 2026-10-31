// Bed mesh math for the heatmap canvas: the Z offset anywhere on the mesh
// (bilinear between the probe points), the colour gradient and the nearest
// probe point. Kept free of Vue / DOM so it can be tested on its own.

export interface MeshLike {
  xs: number[];
  ys: number[];
  z: number[][]; // z[row][col] at (xs[col], ys[row])
}

// Index i with axis[i] <= v <= axis[i + 1] and the fraction between them, clamped to the mesh.
function locate(axis: number[], v: number): [number, number] {
  const n = axis.length;
  if (n < 2 || v <= axis[0]) return [0, 0];
  if (v >= axis[n - 1]) return [n - 2, 1];
  let i = 0;
  while (i < n - 2 && v > axis[i + 1]) i++;
  const span = axis[i + 1] - axis[i];
  return [i, span > 0 ? (v - axis[i]) / span : 0];
}

// Z offset (mm) at bed position (x, y), bilinear between the four surrounding probe points.
export function interpolate(mesh: MeshLike, x: number, y: number): number {
  const { xs, ys, z } = mesh;
  if (!xs.length || !ys.length) return 0;
  if (xs.length === 1 && ys.length === 1) return z[0][0];
  const [c, fx] = xs.length > 1 ? locate(xs, x) : [0, 0];
  const [r, fy] = ys.length > 1 ? locate(ys, y) : [0, 0];
  const c1 = Math.min(c + 1, xs.length - 1);
  const r1 = Math.min(r + 1, ys.length - 1);
  const bottom = z[r][c] * (1 - fx) + z[r][c1] * fx;
  const top = z[r1][c] * (1 - fx) + z[r1][c1] * fx;
  return bottom * (1 - fy) + top * fy;
}

// The probe point closest to (x, y).
export function nearestPoint(mesh: MeshLike, x: number, y: number): { row: number; col: number } {
  let best = { row: 0, col: 0 };
  let bestD = Infinity;
  mesh.ys.forEach((py, row) =>
    mesh.xs.forEach((px, col) => {
      const d = (px - x) ** 2 + (py - y) ** 2;
      if (d < bestD) {
        bestD = d;
        best = { row, col };
      }
    }),
  );
  return best;
}

// Largest deviation from 0, at least 1 µm: the gradient is symmetric around 0.
export function maxDeviation(mesh: MeshLike): number {
  return Math.max(0.001, ...mesh.z.flat().map((v) => Math.abs(v)));
}

// Diverging gradient: blue (bed lower, -maxAbs) - light grey (0) - red (bed higher, +maxAbs).
const LOW: [number, number, number] = [37, 99, 235];
const MID: [number, number, number] = [229, 231, 235];
const HIGH: [number, number, number] = [220, 38, 38];

export function gradientColor(z: number, maxAbs: number): [number, number, number] {
  const t = Math.max(-1, Math.min(1, z / maxAbs));
  const end = t < 0 ? LOW : HIGH;
  const a = Math.abs(t);
  return [0, 1, 2].map((k) => Math.round(MID[k] + (end[k] - MID[k]) * a)) as [number, number, number];
}

// CSS gradient for the legend, the same stops as gradientColor.
export const GRADIENT_CSS = `linear-gradient(to right, rgb(${LOW}), rgb(${MID}), rgb(${HIGH}))`;
