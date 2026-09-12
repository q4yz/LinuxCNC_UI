// Structural guard for throttling the 3D viewer's toolhead-position
// render trigger.
//
// The servo thread streams position at up to 10 Hz, and real hardware
// feedback almost always carries sub-visible floating-point jitter —
// the backend's delta diffing (ServoThreadStateMapper.get_diff_response)
// is correct (it only sends a field when it's numerically different),
// but "numerically different" isn't the same as "visually different",
// so in practice a position delta arrives on close to every tick,
// jogging or not. Each one used to force a full software-rasterized
// WebGL render — expensive enough on a GPU-less target that the
// reported symptom was the viewer dropping to ~3fps or less while
// jogging, when the operator most needs the rest of the UI responsive.
//
// Two independent filters now guard the toolhead marker specifically
// (the toolpath-rebuild and axis-limits-rebuild paths are separate,
// already-narrow triggers, untouched by this):
//   1. A dead-zone — skip the render for sub-visual moves.
//   2. A trailing-edge throttle — cap how often a real move can force
//      a render, with a trailing call so the final position in a
//      burst still gets painted.
//
// Run with: ``node --test frontend/tests/test-toolhead-render-throttle.ts``

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");
const viewerPath = resolve(repoRoot, "frontend/src/components/NgcCoordinateSystemViewer.vue");

function read(): string {
  return readFileSync(viewerPath, "utf-8");
}

test("the toolhead's transform always tracks the latest position, independent of throttling", () => {
  const text = read();
  const fnBody = text.match(/const updateToolheadPosition = \(\) => \{[\s\S]*?\n\}/)?.[0] ?? "";
  assert.ok(fnBody, "expected to find updateToolheadPosition()");
  // toolheadGroup.position.set(...) must run unconditionally, before
  // any dead-zone/throttle check — the mesh must never show a stale
  // position even on a tick that skips forcing a redraw.
  const setIndex = fnBody.indexOf("toolheadGroup.position.set(x, y, z)");
  const deadZoneIndex = fnBody.indexOf("TOOLHEAD_EPSILON_SQ");
  assert.ok(setIndex !== -1, "must call toolheadGroup.position.set(x, y, z)");
  assert.ok(deadZoneIndex !== -1, "must reference the dead-zone threshold");
  assert.ok(setIndex < deadZoneIndex, "position.set must run before the dead-zone/throttle checks, not be skipped by them");
});

test("a sub-visual move is skipped via a squared-distance dead-zone", () => {
  const text = read();
  assert.match(text, /TOOLHEAD_EPSILON_SQ\s*=\s*0\.02\s*\*\s*0\.02/, "dead-zone threshold must exist");
  assert.match(
    text,
    /dx \* dx \+ dy \* dy \+ dz \* dz < TOOLHEAD_EPSILON_SQ/,
    "must compare squared distance against the squared epsilon (avoids a sqrt per tick)",
  );
});

test("real moves are throttled with a trailing-edge timer, not dropped", () => {
  const text = read();
  assert.match(
    text,
    /TOOLHEAD_RENDER_MIN_INTERVAL_MS\s*=\s*150/,
    "must cap position-driven renders to a fixed minimum interval",
  );
  assert.match(text, /let pendingToolheadRenderTimer/, "must track a pending trailing-edge timer");
  assert.match(
    text,
    /pendingToolheadRenderTimer = setTimeout\(/,
    "must schedule a trailing call when a move arrives inside the throttle window",
  );
  // The trailing callback must re-read the position at fire time
  // (not close over the stale value from when it was scheduled),
  // since more updates likely arrived while it was pending.
  assert.match(
    text,
    /pendingToolheadRenderTimer = setTimeout\(\(\) => \{[\s\S]{0,200}const latest = store\.status\.position/,
    "the trailing callback must re-read the latest position, not use a stale closure value",
  );
});

test("the pending trailing timer is cleared on unmount", () => {
  const text = read();
  assert.match(
    text,
    /onBeforeUnmount\(\(\) => \{[\s\S]{0,300}clearTimeout\(pendingToolheadRenderTimer\)/,
    "must clear the pending trailing timer so it can't fire (and call requestRender) after unmount",
  );
});

test("the position watch is no longer deep — position is always wholly reassigned, never mutated in place", () => {
  const text = read();
  assert.match(
    text,
    /watch\(\(\) => store\.status\.position, updateToolheadPosition\)/,
    "the watch must not carry { deep: true } any more",
  );
});
