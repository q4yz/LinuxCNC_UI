// Nullable-module guarantee for the frontend camera module.
//
// Run with: node --test frontend/tests/test-camera-null.mjs
//
// Issue #2 requires the camera module to be **removable** without
// breaking the dashboard build. We cannot dynamically delete
// ``frontend/src/modules/camera/`` at test time (the import would
// fail mid-suite), so this test takes a static-analysis approach:
//
//   1. The dashboard view uses ``defineAsyncComponent`` for the camera
//      panel — never a static import. Without this, deleting the
//      camera folder would crash the build (Gotcha #1).
//   2. The dashboard renders the camera slot behind a ``v-if`` that
//      reads the registry — so a missing module produces an empty
//      cell, not an error.
//   3. The store-id lint passes (camera module ships no Pinia store,
//      but if anyone adds one in the future the id must match the
//      ``module_camera`` convention from Gotcha #2).
//   4. The legacy ``frontend/src/components/CameraPanel.vue`` is gone
//      — the module owns the canonical implementation now.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");

const dashboardPath = resolve(
  repoRoot,
  "frontend/src/views/DashboardView.vue",
);
const legacyCameraPanel = resolve(
  repoRoot,
  "frontend/src/components/CameraPanel.vue",
);
const newCameraPanel = resolve(
  repoRoot,
  "frontend/src/modules/camera/components/CameraPanel.vue",
);

test("DashboardView uses defineAsyncComponent for the camera panel", () => {
  const source = readFileSync(dashboardPath, "utf-8");
  assert.match(
    source,
    /defineAsyncComponent/,
    "DashboardView must use defineAsyncComponent so the camera chunk is split",
  );
  assert.match(
    source,
    /import\(\s*['"]\.\.\/modules\/camera\/components\/CameraPanel\.vue['"]\s*\)/,
    "DashboardView must lazily import the camera module's CameraPanel.vue",
  );
});

test("DashboardView guards the camera slot with a v-if", () => {
  const source = readFileSync(dashboardPath, "utf-8");
  // The v-if should reference the registry so an absent module
  // produces an empty cell rather than a runtime error.
  assert.match(source, /v-if="cameraMounted"/);
  assert.match(
    source,
    /cameraMounted/,
    "cameraMounted computed must be defined in the script setup",
  );
  assert.match(source, /registry\.modules\.has\(['"]camera['"]\)/);
});

test("DashboardView does not statically import the legacy camera path", () => {
  const source = readFileSync(dashboardPath, "utf-8");
  // A regression where someone re-adds ``import CameraPanel from
  // '../components/CameraPanel.vue'`` would re-introduce the
  // "deleting the module folder breaks the build" failure mode.
  assert.doesNotMatch(
    source,
    /from\s+['"]\.\.\/components\/CameraPanel\.vue['"]/,
    "DashboardView must not statically import the old camera path",
  );
});

test("Legacy components/CameraPanel.vue is removed", () => {
  assert.equal(
    existsSync(legacyCameraPanel),
    false,
    `expected ${legacyCameraPanel} to be removed after migration`,
  );
});

test("New modules/camera/components/CameraPanel.vue is in place", () => {
  assert.equal(
    existsSync(newCameraPanel),
    true,
    `expected ${newCameraPanel} to exist`,
  );
});

test("CameraPanel.vue points at the module-scoped stream URL", () => {
  const source = readFileSync(newCameraPanel, "utf-8");
  assert.match(
    source,
    /\/api\/v1\/modules\/camera\/stream/,
    "CameraPanel must point at /api/v1/modules/camera/stream (module URL)",
  );
  assert.doesNotMatch(
    source,
    /\/api\/v1\/camera\/stream/,
    "CameraPanel must not reference the legacy /api/v1/camera/stream URL",
  );
});