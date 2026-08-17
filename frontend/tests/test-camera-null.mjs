// Camera module contract — hard-dependency regression guard.
//
// Run with: node --import ../scripts/vue-test-loader-register.mjs
//             --test test-camera-null.mjs
//
// The camera module is a hard dependency (per the contract
// rewrite, see ``.agent/STATE.md`` § 7). The legacy "removable
// module" guarantee was retired — the dashboard now statically
// imports ``CameraViewer`` from the module folder and the registry
// refuses to mount a module without a non-null ``mainView``. This
// file is now a structural-assertion suite that pins the
// hard-dependency invariants:
//
//   1. The dashboard view statically imports ``CameraViewer`` from
//      the module folder — never via lazy discovery
//      (``defineAsyncComponent`` or ``import.meta.glob(..., { eager:
//      false })``).
//   2. The dashboard still gates the camera slot behind a ``v-if``
//      so the slot is hidden when the registry excludes the module
//      via ``MODULES_ENABLED``.
//   3. The camera store follows the ``module_camera`` convention
//      from Gotcha #2, which is checked by the build's store-id
//      lint.
//   4. The legacy ``frontend/src/components/CameraPanel.vue``
//      wrapper is gone — the module owns the canonical
//      implementation via ``CameraViewer``, exposed through the
//      module's ``mainView``.
//   5. The module's ``index.js`` exports a non-null ``mainView``
//      so the contract test in the registry passes.

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
  "frontend/src/modules/camera/index.ts",
);
const cameraViewer = resolve(
  repoRoot,
  "frontend/src/modules/camera/components/CameraViewer.vue",
);

test("DashboardView statically imports CameraViewer (no lazy discovery)", () => {
  const source = readFileSync(dashboardPath, "utf-8");
  // The camera module is a hard dependency; the dashboard must
  // import it statically. ``panelFor`` and ``defineAsyncComponent``
  // were retired when lazy imports were banned in the contract
  // rewrite (see ``.agent/STATE.md`` § 13).
  assert.doesNotMatch(
    source,
    /panelFor\(\s*['"]camera['"]/,
    "DashboardView must not use the legacy panelFor lazy discovery for the camera module",
  );
  assert.match(
    source,
    /import\s+CameraViewerRaw\s+from\s+['"]\.\.\/modules\/camera\/components\/CameraViewer\.vue['"]/,
    "DashboardView must statically import the camera module's CameraViewer.vue",
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

test("camera/index.js statically imports and exports mainView: CameraViewer", () => {
  const text = readFileSync(cameraIndex, "utf-8");
  // The registry contract: ``mainView`` on the module's default
  // export is what ``App.vue`` and ``registerModuleRoutes`` mount
  // for the route the sidebar resolves to. The no-lazy-imports
  // rule (``.agent/STATE.md`` § 13) bans ``defineAsyncComponent``
  // and dynamic ``import()`` from the module surface, so the
  // module must import its main view statically.
  assert.doesNotMatch(
    text,
    /\bdefineAsyncComponent\s*\(/,
    "camera/index.js must not call defineAsyncComponent (no-lazy-imports rule)",
  );
  assert.doesNotMatch(
    text,
    /import\s*\(\s*["']\.\/components\/CameraViewer\.vue["']\s*\)/,
    "camera/index.js must not dynamic-import CameraViewer.vue",
  );
  assert.match(
    text,
    /import\s+CameraViewer\s+from\s+["']\.\/components\/CameraViewer\.vue["']/,
    "camera/index.js must statically import CameraViewer from the components folder",
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
    "frontend/src/modules/camera/cameraStore.ts",
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