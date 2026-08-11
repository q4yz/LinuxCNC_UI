// Static-structure tests for the tools module.
//
// Run with: node --test frontend/tests/test-tools-module.mjs
//
// The suite validates the public surface and conventions the
// frontend module must satisfy:
//
//   * ``manifest.js`` exposes the documented FrontendModuleManifest
//     fields with ``id="tools"`` and ``settingsPanel: false``.
//   * ``index.js`` follows the same shape as the camera / temperature
//     modules (default export with ``manifest``, ``onLoad``,
//     ``onUnload``).
//   * ``toolStore.js`` declares its Pinia store id as
//     ``module_tools`` per ``MODULE_SYSTEM_ROADMAP.md`` § 12
//     Gotcha #2.
//   * The store is backend-driven — no hard-coded SEED_TOOLS; the
//     tool list comes from ``GET /api/v1/modules/tools/tools`` plus
//     an optional ``state.tools`` event-bus topic (mirrors the
//     temperature module).
//   * The store POSTs spindle + extruder + tool-target commands to
//     the documented module URLs.
//   * The panel renders one chip per tool in the header and a
//     single card body, dispatched by ``selectedTool.type``:
//     spindle_digital / spindle_analog / extruder / heated_bed.
//   * Each per-type card owns its own focused markup.
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
const componentsDir = resolve(toolsDir, "components");

function read(p) {
  return readFileSync(p, "utf-8");
}

test("tools module files exist", () => {
  assert.ok(existsSync(manifestPath), "manifest.js missing");
  assert.ok(existsSync(indexPath), "index.js missing");
  assert.ok(existsSync(storePath), "toolStore.js missing");
  assert.ok(existsSync(panelPath), "components/ToolPanel.vue missing");
  for (const name of [
    "SpindleCard.vue",
    "AnalogSpindleCard.vue",
    "HeaterControls.vue",
    "HeatedBedCard.vue",
    "ExtruderCard.vue",
  ]) {
    assert.ok(
      existsSync(resolve(componentsDir, name)),
      `components/${name} missing`,
    );
  }
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

test("toolStore is backend-driven — no hard-coded SEED_TOOLS", () => {
  const text = read(storePath);
  // The mock fixture array is gone; the store loads from the
  // backend instead. Polls ``/api/v1/modules/tools/tools`` and
  // subscribes to the ``state.tools`` event-bus topic.
  assert.doesNotMatch(text, /SEED_TOOLS/);
  assert.match(text, /\/api\/v1\/modules\/tools\/tools/);
  assert.match(text, /state\.tools/);
  // Polling cadence is exposed via the store surface.
  assert.match(text, /refreshTools/);
  assert.match(text, /DEFAULT_POLL_MS/);
});

test("toolStore actions POST to documented endpoints", () => {
  const text = read(storePath);
  assert.match(text, /\/api\/v1\/modules\/tools\/spindle/);
  assert.match(text, /\/api\/v1\/modules\/tools\/extruder/);
  // The tool-target endpoint is nested under ``/tools/{id}/target``
  // to match the temperature module's ``/sensors/{name}/target``
  // pattern. The store URL-builds with ``encodeURIComponent``.
  assert.match(
    text,
    /\/api\/v1\/modules\/tools\/tools\/\$\{encodeURIComponent\(toolId\)\}\/target/,
  );
});

test("toolStore exposes selection state for the panel header", () => {
  const text = read(storePath);
  // Reactive refs the panel binds against.
  assert.match(text, /selectedToolId/);
  assert.match(text, /selectedTool/);
  // Action the chip-row buttons call on click.
  assert.match(text, /setSelectedToolId/);
});

test("ToolPanel.vue renders chip header + single-card body", () => {
  const text = read(panelPath);
  // Header chip row iterates over the tools list.
  assert.match(text, /v-for="tool in tools"/);
  // Active chip is highlighted; the chip click drives the
  // selection ref.
  assert.match(text, /setSelectedToolId/);
  // Body renders ONE card, dispatched by the selected tool's type.
  assert.match(text, /selectedTool\.type === 'spindle_analog'/);
  assert.match(text, /selectedTool\.type === 'spindle_digital'/);
  assert.match(text, /selectedTool\.type === 'extruder'/);
  assert.match(text, /selectedTool\.type === 'heated_bed'/);
  // Empty-state placeholder when the backend has not reported any
  // tools yet.
  assert.match(text, /No tools configured yet/);
  // Each per-type card is imported and dispatched on the selected
  // tool only — no ``v-for`` over the body.
  assert.doesNotMatch(text, /v-for="tool in toolStore\.tools"/);
});

test("SpindleCard.vue renders digital-spindle controls", () => {
  const text = read(resolve(componentsDir, "SpindleCard.vue"));
  assert.match(text, /Actual RPM/);
  assert.match(text, /Target RPM/);
  assert.match(text, /Reverse/);
  assert.match(text, /Stop/);
  assert.match(text, /Forward/);
  // min_rpm / max_rpm helper text appears when present.
  assert.match(text, /min_rpm/);
  assert.match(text, /max_rpm/);
});

test("AnalogSpindleCard.vue hides feedback tiles", () => {
  const text = read(resolve(componentsDir, "AnalogSpindleCard.vue"));
  assert.match(text, /Analog spindle/);
  assert.match(text, /Enable/);
  assert.match(text, /Disable/);
  assert.doesNotMatch(text, /Actual RPM/);
  assert.doesNotMatch(text, /Target RPM/);
  assert.doesNotMatch(text, /Reverse/);
});

test("HeaterControls.vue renders the shared heat block", () => {
  const text = read(resolve(componentsDir, "HeaterControls.vue"));
  assert.match(text, /Actual Temp/);
  assert.match(text, /Target Temp/);
  assert.match(text, /Set Temp/);
  assert.match(text, /min_temp/);
  assert.match(text, /max_temp/);
});

test("HeatedBedCard.vue is a thin wrapper around HeaterControls", () => {
  const text = read(resolve(componentsDir, "HeatedBedCard.vue"));
  assert.match(text, /import HeaterControls/);
  assert.match(text, /<HeaterControls :tool="tool"/);
});

test("ExtruderCard.vue composes heat + motion in one card", () => {
  const text = read(resolve(componentsDir, "ExtruderCard.vue"));
  // Heat block via the shared component.
  assert.match(text, /import HeaterControls/);
  assert.match(text, /<HeaterControls :tool="tool"/);
  // Motion block — speed + retract/extrude + distance slider.
  assert.match(text, /Speed \(mm\/min\)/);
  assert.match(text, /Retract/);
  assert.match(text, /Extrude/);
  // Logarithmic distance array lives here now (moved out of the
  // panel when the per-type bodies were extracted).
  assert.match(text, /\[\s*0\.1\s*,\s*1\s*,\s*10\s*,\s*50\s*,\s*100\s*\]/);
});

test("DashboardView wires ToolPanel via the nullable panelFor pattern", () => {
  const text = read(dashboardPath);
  assert.match(text, /panelFor\(['"]tools['"]\s*,\s*['"]ToolPanel['"]\)/);
  assert.match(text, /toolsMounted/);
  assert.match(text, /<ToolPanel\s+v-if="toolsMounted"/);
});