// Structural guard for freezing the Dashboard's two live canvases
// (the shared 3D toolpath viewer and the temperature chart) while
// the Dashboard's own scroll container is moving.
//
// Both canvases redraw continuously (the viewer on telemetry
// position updates, the chart on its 10 Hz tick) independently of
// whatever the operator is doing. On a GPU-less target, a redraw
// landing mid-scroll competes with the browser's own scroll-repaint
// work on the same software rasterizer, which is the reported cause
// of scroll performance collapsing specifically while a canvas is
// visible. useDashboardScrollState.ts is a small singleton signal
// DashboardView writes to (on its own ``scroll`` event) and both
// canvas owners read from to pause their redraws during the gesture
// (and its momentum/inertia tail).
//
// Run with: ``node --test frontend/tests/test-dashboard-scroll-freeze.ts``

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");
const src = resolve(repoRoot, "frontend/src");

const read = (rel: string): string => readFileSync(resolve(src, rel), "utf-8");

const composablePath = "composables/useDashboardScrollState.ts";

test("useDashboardScrollState is a module-scope singleton, not per-consumer state", () => {
  const text = read(composablePath);
  // Singleton (state created OUTSIDE the exported function) so every
  // consumer — DashboardView, App.vue, TemperaturePanel — shares the
  // same signal, matching the useMachineOnline pattern already used
  // elsewhere in this codebase.
  assert.ok(
    text.indexOf("const isScrolling") < text.indexOf("export function useDashboardScrollState"),
    "isScrolling must be created outside the composable function (singleton)",
  );
  assert.match(text, /export function useDashboardScrollState/);
  assert.match(text, /markScrolling/, "must expose a way to signal an active scroll");
});

test("useDashboardScrollState debounces back to false after scroll events stop", () => {
  const text = read(composablePath);
  assert.match(text, /SETTLE_MS\s*=\s*150/, "settle window must exist and be short (covers inertia, not indefinite)");
  assert.match(text, /clearTimeout\(settleTimer\)/, "each new scroll event must restart the settle timer");
  assert.match(text, /isScrolling\.value\s*=\s*false/, "must flip back to false once the settle timer fires");
});

test("DashboardView marks scrolling on its own scroll container", () => {
  const text = read("views/DashboardView.vue");
  assert.match(text, /import\s*\{\s*useDashboardScrollState\s*\}/, "must consume the shared composable");
  assert.match(
    text,
    /<div class="h-full overflow-y-auto pr-2" @scroll="markScrolling">/,
    "the actual scrolling element must report its own scroll events — not a wrapper or window",
  );
});

test("App.vue pauses the shared 3D viewer while Dashboard is scrolling", () => {
  const text = read("App.vue");
  assert.match(text, /import\s*\{\s*useDashboardScrollState\s*\}/, "must consume the shared composable");
  assert.match(
    text,
    /isToolpathViewActive\s*=\s*computed\(\s*\(\)\s*=>\s*\(route\.name === ['"]dashboard['"] \|\| route\.name === ['"]jogging['"]\)\s*&&\s*!isScrolling\.value/,
    "the viewer's active flag must also require that Dashboard is not currently scrolling",
  );
});

test("TemperaturePanel skips its chart tick while Dashboard is scrolling", () => {
  const text = read("components/temperature/TemperaturePanel.vue");
  assert.match(text, /import\s*\{\s*useDashboardScrollState\s*\}/, "must consume the shared composable");
  assert.match(
    text,
    /tickHandle = setInterval\(\(\) => \{\s*(?:\/\/[^\n]*\n\s*)*if \(isScrolling\.value\) return/,
    "the interval callback must bail out before updating currentTime (and triggering a chart redraw) while scrolling",
  );
});
