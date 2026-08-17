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
  resolve(repoRoot, "frontend/src/modules/machine/manifest.ts"),
).href;

const storePath = resolve(
  repoRoot,
  "frontend/src/stores/machine.ts",
);
const storeReexportPath = resolve(
  repoRoot,
  "frontend/src/modules/machine/store.ts",
);

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
  // ``machine`` contributes a settings tab so the Settings page
  // renders a Machine tab. The contract requires every manifest
  // to declare the ``sidebar`` field; the machine module ships
  // an empty ``SidebarEntry`` because it lives at the dashboard
  // root rather than as a top-level nav item. The registry
  // filters the entry out by its empty ``id``.
  assert.equal(manifest.settingsPanel, true);
  assert.equal(typeof manifest.sidebar, "object");
  assert.equal(manifest.sidebar.id, "");
});

test("machine store pinia id matches the module_ prefix rule", async () => {
  // Read the file as text and assert the store id is
  // effectively ``module_machine``. The store lives in the
  // runtime-stores layer (``stores/machine.js``); the id is
  // derived from a hardcoded constant (``"machine"``) prefixed
  // with ``module_`` so the file does not depend on
  // ``modules/machine/manifest.js``. The lint script
  // ``frontend/scripts/check-store-ids.mjs`` catches drift
  // between the constant and the manifest at CI time.
  const fs = await import("node:fs/promises");
  const text = await fs.readFile(storePath, "utf-8");
  // The store id is the literal string ``"module_machine"`` (no
  // template-literal indirection so ``stores/`` does not depend
  // on ``modules/machine/manifest.js``). Match either the
  // direct literal or the template-literal form
  // ``module_${...}`` whose prefix interpolates to
  // ``module_``.
  assert.match(
    text,
    /STORE_ID\s*=\s*[`'"]module_|module_machine/,
  );
  assert.match(text, /defineStore\(\s*STORE_ID/);
});

test("machine store re-exports useMachineRefs helper", async () => {
  // The module's ``store.js`` is now a thin re-export of
  // ``stores/machine.js``; the named re-export preserves the
  // ``useMachineRefs`` symbol the module's own components
  // import via the historical ``../store.js`` path.
  const fs = await import("node:fs/promises");
  const text = await fs.readFile(storeReexportPath, "utf-8");
  assert.match(text, /\buseMachineRefs\b/);
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
  // The store id at ``stores/machine.js`` is hardcoded as
  // ``module_machine`` (the manifest's id prefixed with
  // ``module_`` per ``.agent/STATE.md`` § 2). The store body
  // either uses the literal directly or derives it from a
  // constant — both shapes are valid; the lint script
  // ``frontend/scripts/check-store-ids.mjs`` catches drift at
  // CI time.
  const fs = await import("node:fs/promises");
  const manifestText = await fs.readFile(
    resolve(repoRoot, "frontend/src/modules/machine/manifest.ts"),
    "utf-8",
  );
  const storeText = await fs.readFile(storePath, "utf-8");
  assert.match(manifestText, /id:\s*(['"`])machine\1/);
  // The store id is the literal string ``"module_machine"``
  // (either as a direct literal or as a template-literal
  // expression like ``module_${...}`` where the prefix
  // interpolates to ``"module_"``). Match either form.
  assert.match(
    storeText,
    /module_machine|STORE_ID\s*=\s*[`'"]module_/,
  );
  assert.match(storeText, /defineStore\(\s*STORE_ID/);
});

test("machine store composes the servo-thread transport instead of owning the WebSocket", async () => {
  // After the servo/base runtime split, the 10 Hz
  // ``/ws/telemetry`` socket lives in ``stores/servoThread.js``.
  // The store composes that store for telemetry. A
  // regression that re-introduces a ``new WebSocket(wsUrl)`` call
  // back into the store would re-bloat the file to ~700 lines
  // and break the runtime split.
  const fs = await import("node:fs/promises");
  const text = await fs.readFile(storePath, "utf-8");
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
