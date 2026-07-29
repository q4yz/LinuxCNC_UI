// Static-structure tests for the Issue #64 tools module.
//
// Run with: node --test frontend/tests/test-tools-module.mjs
//
// The suite validates the public surface and conventions the new
// frontend module must satisfy:
//
//   * ``manifest.js`` exposes the documented FrontendModuleManifest
//     fields with ``id="tools"`` and ``settingsPanel: false`` (the
//     issue ships the panel as part of the dashboard, not the
//     Settings tab).
//   * ``index.js`` follows the same shape as the camera / temperature
//     modules (default export with ``manifest``, ``onLoad``,
//     ``onUnload``).
//   * ``toolStore.js`` declares its Pinia store id as
//     ``module_tools`` per ``MODULE_SYSTEM_ROADMAP.md`` § 12
//     Gotcha #2.
//   * The store seeds the mock tool array with one spindle
//     (``actual_rpm`` + ``target_rpm`` + ``set_speed``) and one
//     extruder (``set_speed`` + ``distance_index``).
//   * Both store actions POST to the documented module URL
//     (``/api/v1/modules/tools/{spindle,extruder}``).
//   * The dashboard wires the panel into the existing nullable-
//     module panelFor pattern.
//
// Pinia itself isn't available in bare-Node tests, and importing
// the Vue SFC requires Vite — neither is available here. This
// suite therefore stays at the source-text level (same approach
// as ``test-machine-facade.mjs`` and ``test-registry.mjs``) and
// relies on regex checks plus the vite build to validate the
// runtime surface.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");

const toolsDir = resolve(repoRoot, "frontend/src/modules/tools");
const manifestPath = resolve(toolsDir, "manifest.js");
const indexPath = resolve(toolsDir, "index.js");
const storePath = resolve(toolsDir, "toolStore.js");
const panelPath = resolve(toolsDir, "components/ToolPanel.vue");
const dashboardPath = resolve(repoRoot, "frontend/src/views/DashboardView.vue");

function read(p) {
  return readFileSync(p, "utf-8");
}

test("tools module files exist", () => {
  assert.ok(existsSync(manifestPath), "manifest.js missing");
  assert.ok(existsSync(indexPath), "index.js missing");
  assert.ok(existsSync(storePath), "toolStore.js missing");
  assert.ok(existsSync(panelPath), "components/ToolPanel.vue missing");
});

test("manifest exports id='tools', title='Tools', settingsPanel: false", () => {
  const text = read(manifestPath);
  assert.match(text, /id:\s*['"]tools['"]/);
  assert.match(text, /title:\s*['"]Tools['"]/);
  // Issue #64: tools live in the dashboard grid, no Settings tab.
  assert.match(text, /settingsPanel:\s*false/);
  // No sidebar entry — the panel is dashboard-bound.
  assert.doesNotMatch(text, /sidebar:\s*\{/);
});

test("index.js default export has manifest / onLoad / onUnload", () => {
  // Source-level check — Vue SFC imports require Vite, which is
  // not available in a bare-Node ``node --test`` environment.
  const text = read(indexPath);
  assert.match(text, /import\s+manifest\s+from\s+["']\.\/manifest\.js["']/);
  assert.match(text, /import\s+ToolPanel\s+from\s+["']\.\/components\/ToolPanel\.vue["']/);
  assert.match(text, /export\s+default\s*\{/);
  assert.match(text, /\bmanifest\b\s*[,}]/);
  assert.match(text, /onLoad\s*\(/);
  assert.match(text, /onUnload\s*\(/);
  // The named re-exports exist for tooling.
  assert.match(text, /export\s*\{\s*manifest\s*,\s*ToolPanel\s*\}/);
});

test("toolStore.js declares the store id as module_tools via the prefix template", () => {
  const text = read(storePath);
  // The literal ``module_tools`` must NOT appear directly inside
  // ``defineStore('…')`` because that would suggest the store id
  // is hard-coded — we want the lint-friendly concatenation.
  assert.doesNotMatch(text, /defineStore\(\s*['"]module_tools['"]/);
  // The canonical prefix template from the camera/temperature
  // modules: ``module_${manifest.id}`` evaluated against
  // ``manifest.id === 'tools'`` produces the expected literal.
  assert.match(text, /`module_\$\{manifest\.id\}`/);
  // And the manifest must be the tools manifest so the runtime
  // resolution lands on the right id.
  assert.match(text, /import\s+manifest\s+from\s+["']\.\/manifest\.js["']/);
});

test("toolStore seeds one spindle and one extruder mock tool", () => {
  const text = read(storePath);
  // Spindle row carries the three required fields from Issue #64 § 2.
  assert.match(text, /type:\s*['"]spindle['"]/);
  assert.match(text, /actual_rpm/);
  assert.match(text, /target_rpm/);
  assert.match(text, /set_speed/);
  // Extruder row carries its own two required fields.
  assert.match(text, /type:\s*['"]extruder['"]/);
  assert.match(text, /distance_index/);
});

test("toolStore actions POST to /api/v1/modules/tools/{spindle,extruder}", () => {
  const text = read(storePath);
  assert.match(text, /\/api\/v1\/modules\/tools\/spindle/);
  assert.match(text, /\/api\/v1\/modules\/tools\/extruder/);
});

test("ToolPanel.vue iterates toolStore.tools and renders per-type UI", () => {
  const text = read(panelPath);
  // Iteration over the store.
  assert.match(text, /v-for="tool in toolStore\.tools"/);
  // Spindle block.
  assert.match(text, /v-if="tool\.type === 'spindle'"/);
  assert.match(text, /Actual RPM/);
  assert.match(text, /Target RPM/);
  assert.match(text, /Reverse/);
  assert.match(text, /Stop/);
  assert.match(text, /Forward/);
  // Extruder block.
  assert.match(text, /v-else-if="tool\.type === 'extruder'"/);
  assert.match(text, /Retract/);
  assert.match(text, /Extrude/);
  // Logarithmic distance array.
  assert.match(text, /\[\s*0\.1\s*,\s*1\s*,\s*10\s*,\s*50\s*,\s*100\s*\]/);
});

test("DashboardView wires ToolPanel via the nullable panelFor pattern", () => {
  const text = read(dashboardPath);
  assert.match(text, /panelFor\(['"]tools['"]\s*,\s*['"]ToolPanel['"]\)/);
  assert.match(text, /toolsMounted/);
  assert.match(text, /<ToolPanel\s+v-if="toolsMounted"/);
});