// Structural guard for freezing the Dashboard's live temperature
// chart while the Dashboard's own scroll container is moving.
//
// The chart redraws continuously (a 10 Hz tick) independently of
// whatever the operator is doing. On a GPU-less target, a redraw
// landing mid-scroll competes with the browser's own scroll-repaint
// work on the same software rasterizer. useDashboardScrollState.ts is
// a small singleton signal DashboardView writes to (on its own
// ``scroll`` event) that the chart reads from to pause its redraws
// during the gesture (and its momentum/inertia tail).
//
// The shared 3D toolpath viewer used to also live on Dashboard and
// read this same signal, but it was pulled off Dashboard entirely
// (see test-machine-online.ts) — it now lives only on JoggingView,
// which has no scroll container, so App.vue no longer needs this
// composable at all.
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

test("App.vue no longer needs the dashboard-scroll signal — the viewer isn't on Dashboard any more", () => {
  const text = read("App.vue");
  assert.doesNotMatch(
    text,
    /useDashboardScrollState/,
    "App.vue must not import this composable — JoggingView (the viewer's only home now) has no scroll container to freeze against",
  );
  assert.match(
    text,
    /isToolpathViewActive = computed\(\(\) => route\.name === ['"]jogging['"]\)/,
    "the viewer's active flag is just the route check now — no scroll-state gate needed off Dashboard",
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
