// Frontend module-registry tests for the machine module.
//
// Run with: node --test frontend/tests/test-machine-registry.mjs
//
// The machine module's ``index.js`` imports .vue components which
// Vite handles at build time. Under plain ``node --test`` the
// vue imports would fail with ``ERR_UNKNOWN_FILE_EXTENSION``, so
// we test the manifest + the contract surface (a hand-written copy
// of the index.js's exports minus the .vue imports) directly.
//
// For full-stack coverage the ``vite build`` step in CI replaces
// this static check.  ``tests/machine-null.mjs`` adds the
// nullable-module guarantee test (deleting the folder leaves the
// dashboard buildable).

import { test } from "node:test";
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");

const manifestUrl = pathToFileURL(
  resolve(repoRoot, "frontend/src/modules/machine/manifest.js"),
).href;

const storeUrl = pathToFileURL(
  resolve(repoRoot, "frontend/src/modules/machine/store.js"),
).href;

const componentsDir = resolve(
  repoRoot,
  "frontend/src/modules/machine/components",
);

test("machine module manifest has the documented shape", async () => {
  const mod = await import(manifestUrl);
  const manifest = mod.default;

  assert.equal(manifest.id, "machine");
  assert.equal(manifest.title, "Machine");
  assert.equal(typeof manifest.version, "string");
  assert.ok(manifest.description);
  // ``machine`` has no sidebar entry (it lives at the dashboard
  // root rather than as a nav item) and contributes a settings
  // tab so the Settings page renders a Machine tab.
  assert.equal(manifest.settingsPanel, true);
  assert.equal(manifest.sidebar, undefined);
});

test("machine store pinia id matches the module_ prefix rule", async () => {
  // Read the file as text and assert the store id is
  // effectively ``module_machine``. The store follows the same
  // pattern as the temperature module: it constructs the id
  // from ``module_${manifest.id}`` so the manifest is the single
  // source of truth.
  const fs = await import("node:fs/promises");
  const text = await fs.readFile(
    resolve(repoRoot, "frontend/src/modules/machine/store.js"),
    "utf-8",
  );
  // The id is built by ``module_${manifest.id}`` and the store
  // must pass ``STORE_ID`` (or the literal ``"module_machine"``)
  // to ``defineStore``. Either pattern keeps the lint happy.
  assert.match(
    text,
    /const\s+STORE_ID\s*=\s*`module_\$\{manifest\.id\}`/,
    "machine store must build its id from module_${manifest.id}",
  );
  assert.match(text, /defineStore\(\s*STORE_ID/);
});

test("machine store re-exports useMachineRefs helper", async () => {
  const fs = await import("node:fs/promises");
  const text = await fs.readFile(
    resolve(repoRoot, "frontend/src/modules/machine/store.js"),
    "utf-8",
  );
  assert.match(text, /export function useMachineRefs/);
});

test("machine module exposes DroPanel and JogControls in components/", async () => {
  const fs = await import("node:fs/promises");
  const droPanel = resolve(componentsDir, "DroPanel.vue");
  const jogControls = resolve(componentsDir, "JogControls.vue");
  const droStat = await fs.stat(droPanel);
  const jogStat = await fs.stat(jogControls);
  assert.ok(droStat.isFile(), "DroPanel.vue must exist");
  assert.ok(jogStat.isFile(), "JogControls.vue must exist");
});

test("machine manifest matches the store id", async () => {
  const fs = await import("node:fs/promises");
  const manifestText = await fs.readFile(
    resolve(repoRoot, "frontend/src/modules/machine/manifest.js"),
    "utf-8",
  );
  const storeText = await fs.readFile(
    resolve(repoRoot, "frontend/src/modules/machine/store.js"),
    "utf-8",
  );
  // ``manifest.id`` and the store id (``module_<manifest.id>``)
  // must agree. The store builds the id from a template literal
  // (``module_${manifest.id}``) so we check the template rather
  // than the resolved value. Together with the manifest literal
  // this guarantees a typo in either side is caught.
  assert.match(manifestText, /id:\s*(['"`])machine\1/);
  assert.match(
    storeText,
    /STORE_ID\s*=\s*`module_\$\{manifest\.id\}`/,
  );
  assert.match(storeText, /defineStore\(\s*STORE_ID/);
});

test("machine store composes the servo-thread transport instead of owning the WebSocket", async () => {
  // After the servo/base runtime split, the 10 Hz
  // ``/ws/telemetry`` socket lives in ``stores/servoThread.js``.
  // The module store composes that store for telemetry. A
  // regression that re-introduces a ``new WebSocket(wsUrl)`` call
  // back into the module store would re-bloat the file to ~700
  // lines and break the runtime split.
  const fs = await import("node:fs/promises");
  const text = await fs.readFile(
    resolve(repoRoot, "frontend/src/modules/machine/store.js"),
    "utf-8",
  );
  assert.match(
    text,
    /useServoThreadStore\s*\(/,
    "machine store must compose useServoThreadStore",
  );
  assert.doesNotMatch(
    text,
    /new\s+WebSocket\s*\(/,
    "machine store must not instantiate its own WebSocket",
  );
});
