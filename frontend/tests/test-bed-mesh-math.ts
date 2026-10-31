// The bed mesh heatmap math (`src/components/bedmesh/bedMeshMath.ts`):
// bilinear interpolation, nearest probe point, the colour gradient.
//
// Run with: ``node --experimental-strip-types --test frontend/tests/test-bed-mesh-math.ts``

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  gradientColor,
  interpolate,
  maxDeviation,
  nearestPoint,
} from "../src/components/bedmesh/bedMeshMath";

// 3 x 2 probe points, z[row][col] at (xs[col], ys[row])
const mesh = {
  xs: [0, 100, 200],
  ys: [0, 50],
  z: [
    [0.1, 0.0, -0.2],
    [0.3, 0.1, 0.0],
  ],
};

const close = (a: number, b: number) => assert.ok(Math.abs(a - b) < 1e-9, `${a} != ${b}`);

test("the probe points themselves", () => {
  mesh.ys.forEach((y, row) => mesh.xs.forEach((x, col) => close(interpolate(mesh, x, y), mesh.z[row][col])));
});

test("bilinear between the probe points", () => {
  close(interpolate(mesh, 50, 0), 0.05);                     // halfway along the front edge
  close(interpolate(mesh, 0, 25), 0.2);                      // halfway along the left edge
  close(interpolate(mesh, 50, 25), (0.1 + 0.0 + 0.3 + 0.1) / 4);
  close(interpolate(mesh, 150, 25), (0.0 - 0.2 + 0.1 + 0.0) / 4);
});

test("outside the mesh it holds the edge value", () => {
  close(interpolate(mesh, -10, -10), 0.1);
  close(interpolate(mesh, 250, 80), 0.0);
});

test("uneven spacing and a single row", () => {
  close(interpolate({ xs: [0, 10, 100], ys: [5], z: [[0, 1, 0]] }, 55, 5), 0.5);
});

test("nearest probe point", () => {
  assert.deepEqual(nearestPoint(mesh, 140, 40), { row: 1, col: 1 });
  assert.deepEqual(nearestPoint(mesh, 190, 2), { row: 0, col: 2 });
});

test("the gradient: blue lower, grey at 0, red higher, symmetric to the largest deviation", () => {
  const m = maxDeviation(mesh);
  close(m, 0.3);
  assert.deepEqual(gradientColor(0, m), [229, 231, 235]);
  assert.deepEqual(gradientColor(-0.3, m), [37, 99, 235]);
  assert.deepEqual(gradientColor(0.3, m), [220, 38, 38]);
  assert.deepEqual(gradientColor(5, m), [220, 38, 38], "clamped");
  const [r, , b] = gradientColor(0.15, m);
  assert.ok(r > b, "half way up is reddish");
  assert.equal(maxDeviation({ xs: [0], ys: [0], z: [[0]] }), 0.001, "a flat mesh does not divide by 0");
});
