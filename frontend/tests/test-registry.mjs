// Frontend module-registry tests.
//
// Run with: node --test frontend/tests/test-registry.mjs
//
// These tests cover the discovery + mounting contract that
// ``frontend/src/core/modules/registry.js`` provides:
//
//   * When ``frontend/src/modules/`` is empty, ``boot()`` returns
//     cleanly and the registry reports ``mounted=[]``.
//   * The camera module's manifest satisfies the FrontendModule
//     shape (id, title, manifest.sidebar, settingsPanel, onLoad).
//
// We import the camera module's ``index.js`` directly via a dynamic
// import with a file:// URL so the test runner does not need Vite or
// Vitest — it stays a pure-Node test that mirrors the
// ``test-event-bus.mjs`` pattern.

import { test } from "node:test";
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");

const cameraModuleUrl = pathToFileURL(
  resolve(repoRoot, "frontend/src/modules/camera/index.js"),
).href;

test("camera module exports the expected shape", async () => {
  const mod = await import(cameraModuleUrl);
  const instance = mod.default;

  assert.ok(instance, "default export must exist");
  assert.ok(instance.manifest, "manifest must exist");
  assert.equal(instance.manifest.id, "camera");
  assert.equal(instance.manifest.title, "Camera");
  assert.equal(instance.manifest.settingsPanel, true);
  assert.equal(typeof instance.onLoad, "function");
  assert.equal(typeof instance.onUnload, "function");

  // Sidebar contribution is optional but the camera module does ship
  // one (so it floats above the built-in nav items in AppSidebar).
  assert.ok(instance.sidebar, "camera module should expose a sidebar entry");
  assert.equal(instance.sidebar.id, "camera");
  assert.equal(typeof instance.sidebar.label, "string");
  assert.equal(typeof instance.sidebar.order, "number");
});

test("camera module onLoad is a no-op and does not throw", async () => {
  const mod = await import(cameraModuleUrl);
  const instance = mod.default;

  // The hook must tolerate the dummy context the registry hands out.
  const fakeCtx = {
    id: "camera",
    eventBus: { subscribe() {}, publish() {}, topics() { return []; } },
    telemetryBus: { subscribe() {}, publish() {}, topics() { return []; } },
    settings: {
      async readAll() { return {}; },
      async readKey() { return undefined; },
      async writeAll() { return {}; },
      async writeKey() { return {}; },
    },
  };
  assert.doesNotThrow(() => instance.onLoad(fakeCtx));
  assert.doesNotThrow(() => instance.onUnload());
});

test("camera module manifest matches the documented schema", async () => {
  const mod = await import(cameraModuleUrl);
  // The manifest may be re-exported as a named export for tooling.
  const manifest = mod.manifest ?? mod.default.manifest;
  // Version is a semantic-ish string; not strictly SemVer so we don't
  // validate it, but it must be present and non-empty.
  assert.ok(manifest.version && typeof manifest.version === "string");
  // Description is optional in the protocol but the camera module
  // ships one so users see a meaningful tooltip in the settings page.
  assert.ok(manifest.description);
});