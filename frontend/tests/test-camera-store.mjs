// Static-structure tests for the camera store's backend persistence.
//
// Run with: node --test frontend/tests/test-camera-store.mjs
//
// Issue: move camera preferences (rename / flip / mirror / hidden)
// out of browser localStorage and into the per-module settings store
// (``GET/PUT /api/v1/modules/camera/settings``) so the rename follows
// the machine rather than the browser profile. Source-text regex
// checks guard the contract because the Pinia runtime isn't available
// in bare-Node tests — same approach as
// ``test-tools-module.mjs`` / ``test-registry.mjs``. The runtime surface
// is exercised end-to-end by the Vite build and the backend
// ``test_camera_settings.py`` round-trip suite.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");

const cameraDir = resolve(repoRoot, "frontend/src/modules/camera");
const storePath = resolve(cameraDir, "cameraStore.js");
const viewerPath = resolve(cameraDir, "components/CameraViewer.vue");
const settingsPath = resolve(cameraDir, "components/CameraSettings.vue");

function read(p) {
  return readFileSync(p, "utf-8");
}

test("camera module files exist", () => {
  assert.ok(existsSync(storePath), "cameraStore.js missing");
  assert.ok(existsSync(viewerPath), "CameraViewer.vue missing");
  assert.ok(existsSync(settingsPath), "CameraSettings.vue missing");
});

test("cameraStore wires the per-module settings client", () => {
  const text = read(storePath);
  assert.match(
    text,
    /import\s*\{\s*createModuleSettings\s*\}\s*from\s*["']\.\.\/\.\.\/core\/modules\/settings\.js["']/,
    "cameraStore.js must import createModuleSettings from the canonical settings factory",
  );
  assert.match(
    text,
    /createModuleSettings\(\s*manifest\.id\s*\)/,
    "cameraStore.js must build the client from manifest.id (module_camera)",
  );
});

test("cameraStore no longer touches localStorage", () => {
  const text = read(storePath);
  // The legacy localStorage key from the original implementation
  // must be gone; a regression here would mean a rename is lost when
  // the operator opens the UI from a different browser.
  assert.doesNotMatch(
    text,
    /linuxcnc\.camera\.preferences/,
    "cameraStore.js must not reference the old localStorage key",
  );
  assert.doesNotMatch(
    text,
    /window\.localStorage/,
    "cameraStore.js must not read window.localStorage",
  );
});

test("cameraStore uses the module_ store-id prefix", () => {
  const text = read(storePath);
  // Store ids match ``^module_[a-z][a-z0-9_]+$`` per the lint rule.
  assert.match(
    text,
    /`module_\$\{manifest\.id\}`/,
    "store id must be built from module_${manifest.id}",
  );
  assert.match(text, /defineStore\(\s*STORE_ID/);
});

test("cameraStore validates the four editable preference keys", () => {
  const text = read(storePath);
  // The whitelist allows camelCase keys (``customName`` + three
  // booleans). ``name`` from the legacy implementation is gone.
  assert.match(text, /EDITABLE_KEYS\s*=\s*new Set\(/);
  for (const key of ["customName", "flip", "mirror", "hidden"]) {
    assert.match(
      text,
      new RegExp(`['"\`]${key}['"\`]`),
      `EDITABLE_KEYS must include ${key}`,
    );
  }
  // ``name`` was the legacy field name and must not sneak back in.
  assert.doesNotMatch(text, /EDITABLE_KEYS[^]*['"`]name['"`]/);
});

test("cycleCamera filters hidden devices out of the rotation", () => {
  const text = read(storePath);
  // The cycle helper must consult the preferences map for the
  // ``hidden`` flag, otherwise hiding a camera has no effect on the
  // Switch Camera button.
  assert.match(
    text,
    /function\s+cycleCamera\s*\(/,
    "cycleCamera must be defined on the store",
  );
  assert.match(
    text,
    /hidden\s*[!=]==?\s*true/,
    "cycleCamera must check the hidden flag in its filter",
  );
  assert.match(
    text,
    /visibleDevices/,
    "cycleCamera must use the visibleDevices helper that filters hidden rows",
  );
});

test("updatePreference schedules a debounced PUT and never blocks the UI", () => {
  const text = read(storePath);
  // The 400 ms debounce must be wired through setTimeout; the
  // constants must be visible at the top of the file.
  assert.match(
    text,
    /PREFERENCE_DEBOUNCE_MS\s*=\s*400/,
    "debounce constant must be 400 ms",
  );
  assert.match(
    text,
    /setTimeout\(\s*writeNow\s*,\s*PREFERENCE_DEBOUNCE_MS\s*\)/,
    "updatePreference must schedule the debounced flush",
  );
  // The store must optimistically update the in-memory ref so the
  // operator sees their change before the round-trip finishes.
  assert.match(
    text,
    /function\s+updatePreference\(/,
    "updatePreference must exist",
  );
});

test("cameraStore exposes a flushPendingPreferenceWrite for unmount safety", () => {
  const text = read(storePath);
  assert.match(
    text,
    /flushPendingPreferenceWrite/,
    "flushPendingPreferenceWrite must be exposed so a 399 ms-old rename isn't lost on navigation",
  );
  // And it must be returned from the setup function so the viewer
  // can call it from onBeforeUnmount.
  assert.match(text, /flushPendingPreferenceWrite[\s\S]*\}\s*;/m);
});

test("CameraSettings.vue renders the hide-from-cycle checkbox", () => {
  const text = read(settingsPath);
  assert.match(
    text,
    /preferenceFor\(device\.id\)\.hidden/,
    "CameraSettings must bind the hidden flag from the store",
  );
  assert.match(
    text,
    /Hide from cycle/,
    "CameraSettings must render the Hide-from-cycle label",
  );
  // The wire format maps ``hidden`` to the snake_case backend field
  // by going through ``updatePreference(id, 'hidden', value)``.
  assert.match(
    text,
    /updateBooleanPreference\(device\.id,\s*['"]hidden['"]/,
  );
});

test("CameraSettings.vue shows a loading placeholder while preferences hydrate", () => {
  const text = read(settingsPath);
  assert.match(
    text,
    /preferencesHydrated/,
    "CameraSettings must read the preferencesHydrated flag from the store",
  );
  assert.match(
    text,
    /Loading preferences…/,
    "CameraSettings must show a placeholder while the backend read is in flight",
  );
});

test("CameraViewer.vue auto-cycles when the active camera is hidden", () => {
  const text = read(viewerPath);
  // A watcher must step forward via cycleCamera when the active id
  // becomes hidden so the viewer does not get stuck on a black image
  // after the operator hides the current feed.
  assert.match(
    text,
    /watch\(\s*\(\)\s*=>\s*\[\s*activeCameraId\.value[\s\S]+store\.cycleCamera/,
  );
  // And the unmount hook must flush any pending PUT before tearing
  // down so a 399 ms-old rename survives navigation.
  assert.match(
    text,
    /flushPendingPreferenceWrite/,
    "CameraViewer must flush pending preference writes on unmount",
  );
});
