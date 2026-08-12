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

test("updatePreference fires an immediate (debounce-free) PUT through the serialised-write chain", () => {
  const text = read(storePath);
  // The 400 ms debounce was removed: an operator typing into a
  // single form never produced bursts worth coalescing, and the
  // optional serialised-write chain keeps every PUT ordered on the
  // wire without a sleep timer.
  assert.doesNotMatch(
    text,
    /PREFERENCE_DEBOUNCE_MS/,
    "debounce constant must not exist; remove the SETTLE/DEBOUNCE_TIMER state machine",
  );
  assert.doesNotMatch(
    text,
    /setTimeout\s*\(\s*writeNow/,
    "updatePreference must not schedule a setTimeout — the write fires immediately through writePreferences",
  );
  // The store must optimistically update the in-memory ref so the
  // operator sees their change before the round-trip finishes.
  assert.match(
    text,
    /function\s+updatePreference\(/,
    "updatePreference must exist",
  );
  // Each keystroke produces one PUT, chained off the previous so
  // they never overlap on the wire.
  assert.match(
    text,
    /writePreferences\s*\(/,
    "updatePreference must dispatch through the serialised writePreferences helper",
  );
  assert.match(
    text,
    /function\s+writePreferences\s*\(/,
    "writePreferences helper must exist to chain writes",
  );
});

test("cameraStore exposes an awaitInFlightPreferenceWrite for unmount safety", () => {
  const text = read(storePath);
  assert.match(
    text,
    /awaitInFlightPreferenceWrite/,
    "awaitInFlightPreferenceWrite must be exposed so the most recent keystroke survives navigation",
  );
  // And it must be returned from the setup function so the viewer
  // can call it from onBeforeUnmount.
  assert.match(text, /awaitInFlightPreferenceWrite[\s\S]*\}\s*;/m);
  // The old debounce-era name must not appear as a callable identifier
  // — that would reintroduce the misleading flush-pending-snapshot
  // semantics. We allow it inside JSDoc / doc-comment text via the
  // ``function`` / ``\.`` boundary so historical references in
  // comments do not trip the test.
  assert.doesNotMatch(
    text,
    /(?:function\s+|await\s+|store\.\s*|\.\s*)flushPendingPreferenceWrite\b/,
    "flushPendingPreferenceWrite must not be referenced as a callable; rename is permanent",
  );
});

test("cameraStore exposes deleteIpCamera that clears the URL and the preference row", () => {
  const text = read(storePath);
  // The action must exist and be exposed on the store surface.
  assert.match(
    text,
    /function\s+deleteIpCamera\s*\(/,
    "deleteIpCamera must be defined on the store",
  );
  assert.match(
    text,
    /deleteIpCamera[\s\S]*\}\s*;/m,
    "deleteIpCamera must be returned from the setup function",
  );
  // Non-IP callers must be refused (USB cameras must not be removable
  // from this surface).
  assert.match(
    text,
    /device\.source\s*!==\s*["']ip["']/,
    "deleteIpCamera must refuse non-IP callers",
  );
  // The preference row for the removed camera must be dropped in the
  // same writeAll that clears the URL so the persisted preferences
  // never orphan the removed camera's custom name.
  assert.match(
    text,
    /delete\s+next\[device\.id\]/,
    "deleteIpCamera must drop the per-device preference row",
  );
  assert.match(
    text,
    /deleteIpCamera[\s\S]*?writeAll\s*\(/,
    "deleteIpCamera must persist via settings.writeAll in the same round-trip",
  );
  // The URL-clearing branch is now keyed on ``device.historical``;
  // the dedicated historical-safety test pins that contract.
  assert.match(
    text,
    /ip_camera_url\s*:\s*["']["']/,
    "deleteIpCamera must include an empty-string URL branch for the currently-active row",
  );
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

test("coercePreference reads the backend's snake_case custom_name (regression for issue #<this one>)", () => {
  // The backend Pydantic model serialises ``custom_name`` as
  // snake_case. An earlier version of this helper read
  // ``value.customName`` (camelCase) and dropped the value to ``""``
  // on every reload, which made the custom name appear to be lost
  // between page navigations even though it was persisted under
  // snake_case on disk. Pin the snake_case read so the typo cannot
  // return.
  const text = read(storePath);
  assert.match(
    text,
    /value\.custom_name\s*===\s*["']string["']/,
    "coercePreference must read the backend's snake_case custom_name field",
  );
  assert.doesNotMatch(
    text,
    /value\.customName\s*===\s*["']string["']/,
    "coercePreference must not read the camelCase customName — that drops the backend's snake_case value to ''",
  );
  // The wire format produced by serializePreferences is unchanged
  // (camelCase in-memory → snake_case on the wire).
  assert.match(
    text,
    /typeof\s+pref\.customName\s*===\s*["']string["']/,
    "serializePreferences must keep writing the camelCase customName to snake_case custom_name",
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
  // And the unmount hook must await the in-flight PUT before tearing
  // down so the most recent keystroke survives navigation.
  assert.match(
    text,
    /awaitInFlightPreferenceWrite/,
    "CameraViewer must await the in-flight preference write on unmount",
  );
});

test("mergeStoredCamerasIntoDevices folds orphan preference keys into the device list", () => {
  // When the operator changes the IP camera URL, the previous key
  // (``ip_camera_url``) stops appearing in /devices but its
  // custom-name row stays in the preferences map. Without the merge,
  // those rows are orphaned and the operator cannot rename / hide /
  // remove them. The merge folds them back in as ``historical``
  // entries so the settings panel stays usable.
  const text = read(storePath);
  assert.match(
    text,
    /function\s+mergeStoredCamerasIntoDevices/,
    "store must define a helper that merges stored preference keys",
  );
  assert.match(
    text,
    /mergeStoredCamerasIntoDevices\s*\(\s*\)/,
    "hydratePreferences must invoke the merge after loading",
  );
  // Synthetic entries must be flagged historical so cycling skips them.
  assert.match(
    text,
    /historical\s*:\s*[^,}]+/,
    "synthetic entries must be flagged historical so they can be filtered out of cycling",
  );
});

test("visibleDevices filters out historical cameras (Switch Camera skips offline IPs)", () => {
  // historical IP cams have no live stream — activating one would
  // point the viewer at an id the backend has never heard of. The
  // cycle helper must exclude them.
  const text = read(storePath);
  assert.match(
    text,
    /visibleDevices[\s\S]{0,200}!device\.historical/,
    "visibleDevices must filter historical entries so the camera cycler skips them",
  );
});

test("CameraSettings.vue marks historical entries with an offline badge", () => {
  // The operator must be able to tell live from stored entries in
  // the settings panel at a glance.
  const text = read(settingsPath);
  assert.match(
    text,
    /device\.historical/,
    "CameraSettings must render an offline indicator keyed on device.historical",
  );
});

test("deleteIpCamera on a historical entry preserves the current ip_camera_url", () => {
  // Removing an offline (historical) IP-cam row must NOT wipe the
  // currently-configured URL. Hard-coding ``ip_camera_url: ""`` would
  // silently break the live stream every time the operator cleans
  // up an orphan.
  const text = read(storePath);
  assert.match(
    text,
    /device\.historical/,
    "deleteIpCamera must consult the historical flag to decide URL handling",
  );
  // And it must read the active URL before deciding whether to clear.
  assert.match(
    text,
    /settings\.readAll\s*\(\s*\)/,
    "deleteIpCamera must read the active URL before deciding whether to clear it",
  );
});
