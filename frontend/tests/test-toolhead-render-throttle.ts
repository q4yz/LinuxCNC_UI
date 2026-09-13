// Structural guard for the 3D viewer's diagnostic instrumentation.
//
// The viewer previously throttled the toolhead-position render trigger
// (a dead-zone + trailing-edge timer) to cope with the servo thread's
// up-to-10Hz position stream. That throttle hid the actual behavior
// instead of explaining it, so it has been removed in favor of
// unconditional, logged renders: every performance-sensitive path now
// logs when it fires, so real hardware behavior (does the viewer
// render constantly even at rest? does a rebuild path fire when it
// shouldn't?) can be observed directly instead of guessed at.
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

test("the toolhead-position dead-zone/throttle has been fully removed", () => {
  const text = read();
  assert.doesNotMatch(text, /TOOLHEAD_EPSILON_SQ/, "dead-zone threshold must no longer exist");
  assert.doesNotMatch(text, /TOOLHEAD_RENDER_MIN_INTERVAL_MS/, "throttle interval must no longer exist");
  assert.doesNotMatch(text, /pendingToolheadRenderTimer/, "trailing-edge timer must no longer exist");
  assert.doesNotMatch(text, /lastRenderedToolheadPosition/, "throttle's last-position cache must no longer exist");
  assert.doesNotMatch(text, /lastToolheadRenderAt/, "throttle's last-render timestamp must no longer exist");
});

test("updateToolheadPosition unconditionally sets position and requests a render, logging every call", () => {
  const text = read();
  const fnBody = text.match(/const updateToolheadPosition = \(\) => \{[\s\S]*?\n\}/)?.[0] ?? "";
  assert.ok(fnBody, "expected to find updateToolheadPosition()");
  assert.match(fnBody, /toolheadGroup\.position\.set\(x, y, z\)/, "must set the toolhead's transform every call");
  assert.match(
    fnBody,
    /console\.count\(['"]\[NgcViewer] updateToolheadPosition/,
    "must count every invocation so real-hardware call frequency is observable in devtools",
  );
  assert.match(fnBody, /requestRender\(\)/, "must request a render unconditionally, with no dead-zone/throttle gate");
});

test("the position watch is not deep — position is always wholly reassigned, never mutated in place", () => {
  const text = read();
  assert.match(
    text,
    /watch\(\(\) => store\.status\.position, updateToolheadPosition\)/,
    "the watch must not carry { deep: true }",
  );
});

test("one-time/rebuild paths (init, limits, toolpath load/redraw/rebuild, WCS marker) each log when triggered", () => {
  const text = read();
  assert.match(text, /console\.log\(['"]\[NgcViewer] initThreeJS\(\)/, "initThreeJS must log — should fire once for the shared instance's lifetime");
  assert.match(text, /console\.log\(['"]\[NgcViewer] setMachineLimits\(\)/, "setMachineLimits must log — should fire once now that axes are static-fetched");
  assert.match(text, /console\.log\(['"]\[NgcViewer] loadProgramToolpath\(\)/, "loadProgramToolpath must log");
  assert.match(text, /console\.log\(['"]\[NgcViewer] redrawToolpath\(\)/, "redrawToolpath must log — must not fire during a plain jog with no loaded program");
  assert.match(text, /console\.log\(`\[NgcViewer] replaceToolpathMesh\(\)/, "replaceToolpathMesh must log the segment count it rebuilds");
  assert.match(text, /console\.log\(['"]\[NgcViewer] updateWcsMarker\(\)/, "updateWcsMarker must log");
});

test("the actual WebGL render call is logged with a timestamp for rate observation", () => {
  const text = read();
  assert.match(
    text,
    /console\.log\(`\[NgcViewer] renderer\.render\(\) at t=\$\{performance\.now\(\)\.toFixed\(1\)\}ms`\)/,
    "the render() call site must log a performance.now() timestamp so real render rate can be measured",
  );
  const renderBlock = text.match(/if \(renderer && scene && camera\) \{[\s\S]*?\n\s*\}/)?.[0] ?? "";
  assert.ok(renderBlock.indexOf("console.log") < renderBlock.indexOf("renderer.render(scene, camera)"), "must log immediately before the actual render call");
});

test("the toolpath-rebuild watchers log their source and payload before deciding whether to redraw", () => {
  const text = read();
  assert.match(
    text,
    /watch\(\(\) => baseThreadProgress\.value\?\.motionLine, \(line\) => \{[\s\S]{0,200}console\.log\(['"]\[NgcViewer] motionLine watch fired/,
    "the motionLine watch must log on every fire, before the lastLoadedFilename guard",
  );
  assert.match(
    text,
    /console\.log\(['"]\[NgcViewer] g5x\/g92-offset watch fired/,
    "the g5x/g92-offset watch must log on every fire — if this logs during a plain jog with no WCS change, that's a real reactivity bug, not just noise",
  );
});
