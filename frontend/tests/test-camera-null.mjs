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
//   3. The camera store follows the ``module_camera`` convention from
//      Gotcha #2, which is checked by the build's store-id lint.
//   4. The legacy ``frontend/src/components/CameraPanel.vue`` wrapper
//      is gone — the module owns the canonical implementation via
//      ``CameraViewer``, exposed through the module's ``mainView``.
//   5. The module's ``index.js`` exports a ``mainView`` so
//      ``App.vue`` and ``registerModuleRoutes`` resolve the camera
//      route deterministically (no file-naming heuristics).

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
const cameraIndex = resolve(
  repoRoot,
  "frontend/src/modules/camera/index.js",
);
const cameraViewer = resolve(
  repoRoot,
  "frontend/src/modules/camera/components/CameraViewer.vue",
);

test("DashboardView uses defineAsyncComponent for the camera viewer", () => {
  const source = readFileSync(dashboardPath, "utf-8");
  assert.match(
    source,
    /defineAsyncComponent/,
    "DashboardView must use defineAsyncComponent so the camera chunk is split",
  );
  assert.match(
    source,
    /panelFor\(\s*['"]camera['"]\s*,\s*['"]CameraViewer['"]\s*\)/,
    "DashboardView must lazily resolve the camera module's CameraViewer.vue",
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

test("modules/camera/components/CameraPanel.vue is removed in favor of mainView", () => {
  // The wrapper ``CameraPanel.vue`` was a 1:1 pass-through to
  // ``CameraViewer.vue``. With the module now exporting
  // ``mainView: CameraViewer``, the wrapper is dead weight — the
  // registry-driven route resolves to ``CameraViewer`` directly.
  assert.equal(
    existsSync(newCameraPanel),
    false,
    `expected ${newCameraPanel} to be removed (mainView replaces it)`,
  );
});

test("camera/index.js exports mainView: CameraViewer", () => {
  const text = readFileSync(cameraIndex, "utf-8");
  // The registry contract: ``mainView`` on the module's default
  // export is what ``App.vue`` and ``registerModuleRoutes`` mount
  // for the route the sidebar resolves to. Without it the camera
  // page falls back to the alphabetical glob discovery which used
  // to pick the (now-deleted) CameraPanel.vue.
  //
  // The camera module loads ``CameraViewer`` lazily through
  // ``defineAsyncComponent`` so removing the module folder stays
  // a no-op for the registry bootstrap (see camera/index.js comment).
  assert.match(
    text,
    /import\(["']\.\/components\/CameraViewer\.vue["']\)/,
    "camera/index.js must dynamic-import the CameraViewer component",
  );
  assert.match(
    text,
    /mainView:\s*CameraViewer\b/,
    "camera/index.js must export mainView: CameraViewer",
  );
});

test("CameraViewer.vue points at the module-scoped stream URL", () => {
  const source = readFileSync(cameraViewer, "utf-8");
  assert.match(
    source,
    /\/api\/v1\/modules\/camera\/stream/,
    "CameraViewer must point at /api/v1/modules/camera/stream (module URL)",
  );
  assert.doesNotMatch(
    source,
    /\/api\/v1\/camera\/stream/,
    "CameraViewer must not reference the legacy /api/v1/camera/stream URL",
  );
});

test("CameraStore persists preferences via the module settings client", () => {
  // Camera preferences (rename / flip / mirror / hide) live in the
  // backend ``/api/v1/modules/camera/settings`` payload so the rename
  // follows the machine, not the browser. Regression guard: a future
  // commit that brings back ``window.localStorage`` would silently
  // re-introduce the per-browser persistence problem.
  const cameraStorePath = resolve(
    repoRoot,
    "frontend/src/modules/camera/cameraStore.js",
  );
  const text = readFileSync(cameraStorePath, "utf-8");
  assert.match(
    text,
    /import\s*\{\s*createModuleSettings\s*\}\s*from/,
    "cameraStore.js must import the canonical settings client factory",
  );
  assert.match(
    text,
    /createModuleSettings\(\s*manifest\.id\s*\)/,
    "cameraStore.js must build the settings client from manifest.id",
  );
  assert.doesNotMatch(
    text,
    /window\.localStorage/,
    "cameraStore.js must not read window.localStorage (migration to backend done)",
  );
  // Debouncing was deliberately removed — a single operator typing
  // into a single form does not produce bursts worth coalescing.
  // Writes are instead serialised through the ``writePreferences``
  // chain so they never overlap on the wire and the server receives
  // them in order. The tripwire below forbids bringing the debounce
  // back without a deliberate decision.
  assert.doesNotMatch(
    text,
    /PREFERENCE_DEBOUNCE_MS/,
    "cameraStore.js must not bring back the 400 ms debounce; writes are serialised through writePreferences instead",
  );
  assert.match(
    text,
    /writePreferences/,
    "cameraStore.js must serialise writes via the writePreferences helper",
  );
});