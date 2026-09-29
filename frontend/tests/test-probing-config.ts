// Tests for ``frontend/src/config/probing.ts`` — the mapping from a
// probing-panel cycle onto an ``.ngc`` macro in ``macros/`` and its
// positional arguments. The argument order has to match each macro's
// ``(Call: ...)`` header exactly; a swapped pair silently probes in
// the wrong direction or with the wrong distance on real hardware.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");

const { buildProbeCall, probeCycleFields } = await import(
  pathToFileURL(resolve(repoRoot, "frontend/src/config/probing.ts")).href
);

const settings = { probeDiameter: 4, feedrate: 100 };

test("inside edges probe toward the named wall", () => {
  const v = { searchDist: 10 };
  assert.deepEqual(buildProbeCall("edge-right", "inside", settings, v), {
    macro: "probe_edge", args: [1, 1, 4, 10, 100],
  });
  assert.deepEqual(buildProbeCall("edge-left", "inside", settings, v).args, [1, -1, 4, 10, 100]);
  assert.deepEqual(buildProbeCall("edge-top", "inside", settings, v).args, [2, 1, 4, 10, 100]);
  assert.deepEqual(buildProbeCall("edge-bottom", "inside", settings, v).args, [2, -1, 4, 10, 100]);
});

test("outside edges probe back toward the part (direction flipped)", () => {
  const v = { searchDist: 10 };
  assert.deepEqual(buildProbeCall("edge-right", "outside", settings, v).args, [1, -1, 4, 10, 100]);
  assert.deepEqual(buildProbeCall("edge-top", "outside", settings, v).args, [2, -1, 4, 10, 100]);
});

test("inside corners never pre-move (overlap forced to 0)", () => {
  assert.deepEqual(
    buildProbeCall("corner-tl", "inside", settings, { searchDist: 8, overlap: 99 }),
    { macro: "probe_corner", args: [-1, 1, 4, 8, 100, 0] },
  );
  assert.deepEqual(probeCycleFields("corner-tl", "inside").map((f) => f.key), ["searchDist"]);
});

test("outside corners flip both directions and pass the overlap", () => {
  assert.deepEqual(
    buildProbeCall("corner-tl", "outside", settings, { searchDist: 8, overlap: 12 }).args,
    [1, -1, 4, 8, 100, 12],
  );
  assert.deepEqual(
    buildProbeCall("corner-br", "outside", settings, { searchDist: 8, overlap: 12 }).args,
    [-1, 1, 4, 8, 100, 12],
  );
  assert.deepEqual(probeCycleFields("corner-br", "outside").map((f) => f.key), ["searchDist", "overlap"]);
});

test("circle and rectangle cycles match their macros' call headers", () => {
  assert.deepEqual(buildProbeCall("circle", "inside", settings, { maxRadius: 15 }), {
    macro: "probe_circle_inside", args: [4, 15, 100],
  });
  assert.deepEqual(
    buildProbeCall("circle", "outside", settings, { bossDiameter: 30, zDrop: 5, clearance: 6 }),
    { macro: "probe_circle_outside", args: [30, 5, 6, 100] },
  );
  assert.deepEqual(buildProbeCall("rect", "inside", settings, { maxX: 20, maxY: 25 }), {
    macro: "probe_rect_inside", args: [20, 25, 100],
  });
  assert.deepEqual(
    buildProbeCall("rect", "outside", settings, { width: 40, length: 50, zDrop: 5, clearance: 6 }),
    { macro: "probe_rect_outside", args: [40, 50, 5, 6, 100] },
  );
});

test("every mapped macro exists and takes exactly as many arguments as we pass", () => {
  const cases = [
    ["edge-top", "inside"], ["corner-tl", "outside"],
    ["circle", "inside"], ["circle", "outside"],
    ["rect", "inside"], ["rect", "outside"],
  ];
  for (const [cycle, mode] of cases) {
    const values = Object.fromEntries(probeCycleFields(cycle, mode).map((f) => [f.key, f.default]));
    const call = buildProbeCall(cycle, mode, settings, values);
    const body = readFileSync(resolve(repoRoot, "macros", `${call.macro}.ngc`), "utf-8");
    const header = body.match(/\(Call:[^)]*?call((?:\s*\[[^\]]*\])*)/i);
    assert.ok(header, `${call.macro}.ngc has a (Call: ...) header`);
    const documented = header[1].match(/\[[^\]]*\]/g) ?? [];
    assert.equal(call.args.length, documented.length, `${call.macro} argument count`);
    assert.ok(call.args.every((a) => Number.isFinite(a)), `${call.macro} args are all numbers`);
  }
});
