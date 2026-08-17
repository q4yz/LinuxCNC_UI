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
//   * The store is backend-driven — the tool list comes from the
//     shared base-thread snapshot (``stores/baseThread.js``); no
//     hard-coded seed list, no own polling interval.
//   * Every write action goes through the OpenAPI-generated
//     ``ModulesToolsService`` client. The store never hand-rolls
//     ``fetch`` calls (see ``.agent/context/LESSONS_LEARNED.md``
//     § 2.7). Errors are routed through ``describeError``.
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
const manifestPath = resolve(toolsDir, "manifest.ts");
const indexPath = resolve(toolsDir, "index.ts");
const storePath = resolve(toolsDir, "toolStore.ts");
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
  // The contract requires every manifest to declare the
  // ``sidebar`` field, even when the module does not contribute a
  // nav entry. The manifest ships an empty ``SidebarEntry`` the
  // registry filters out by ``id``.
  assert.match(
    text,
    /sidebar:\s*\{\s*id:\s*['"]{2}/,
    "manifest must declare an empty sidebar entry (contract requirement)",
  );
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

test("toolStore consumes the base-thread snapshot — no own polling", () => {
  const text = read(storePath);
  // The mock fixture array is gone; the store reads tools from
  // the shared base-thread snapshot
  // (``stores/baseThread.js``) so the dashboard only issues one
  // HTTP request per second for every slow stream.
  assert.doesNotMatch(text, /SEED_TOOLS/);
  assert.match(text, /useBaseThreadStore\s*\(/);
  assert.match(text, /refreshTools/);
  // The store must NOT own a polling interval — the base-thread
  // store fires every 1 s, no second ``setInterval`` is needed.
  assert.doesNotMatch(
    text,
    /setInterval\s*\(\s*refreshTools/,
    "toolStore must not own a polling interval",
  );
});

test("toolStore never hand-rolls HTTP — every call goes through the toolsFacade", () => {
  // See ``.agent/context/LESSONS_LEARNED.md`` § 2.7. The tripwire
  // pattern matches the temperature module's hand-rolled
  // ``fetch`` in TemperaturePanel.vue (a separate cleanup pass).
  //
  // After the anti-corruption layer refactor the store does NOT
  // import the generated ``ModulesToolsService`` directly — it
  // routes every write through ``toolsFacade`` so wire-shape
  // knowledge stays in the mapper.
  const text = read(storePath);
  // No raw fetch / postJson / XMLHttpRequest in the store. Allow
  // ``useBaseThreadStore`` (which itself uses the generated
  // ``BaseThreadService``) — that's the exception, not the rule.
  assert.doesNotMatch(text, /\bfetch\s*\(/);
  assert.doesNotMatch(text, /\bpostJson\s*\(/);
  assert.doesNotMatch(text, /XMLHttpRequest/);
  // And no hand-rolled URL strings — the generated client owns
  // those.
  assert.doesNotMatch(text, /\/api\/v1\/modules\/tools\//);
  // The store imports ``toolsFacade`` and routes every write
  // action through it.
  assert.match(
    text,
    /import\s+\{[^}]*toolsFacade[^}]*\}\s+from\s+["'][^"']*facades\/toolsFacade/,
  );
  assert.match(text, /toolsFacade\.controlSpindle\s*\(/);
  assert.match(text, /toolsFacade\.controlExtruder\s*\(/);
  assert.match(text, /toolsFacade\.setTarget\s*\(/);
  // Errors flow through the canonical describeError helper
  // (``core/error-format.js``) so the console store sees the
  // same envelope shape as every other module.
  assert.match(
    text,
    /import\s+\{[^}]*describeError[^}]*\}\s+from\s+["'][^"']*core\/error-format/,
  );
  assert.match(text, /describeError\s*\(/);
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
  // Header chip row iterates over the typed entity surface.
  assert.match(text, /v-for="tool in toolList\.all\(\)"/);
  // Empty-state placeholder when no entities yet.
  assert.match(text, /toolList\.size\s*>\s*0/);
  // Active chip is highlighted; the chip click drives the
  // selection ref.
  assert.match(text, /setSelectedToolId/);
  // Body renders ONE card, dispatched by the selected tool's
  // ``static type`` (compared against the class constant so a
  // string-typo in the dispatch chain is caught at import time).
  // Both spindle variants are in the chain so the analog card can
  // come back without a panel rewrite.
  assert.match(text, /selectedTool\.type === SpindleAnalog\.type/);
  assert.match(text, /selectedTool\.type === SpindleDigital\.type/);
  assert.match(text, /selectedTool\.type === Extruder\.type/);
  assert.match(text, /selectedTool\.type === HeaterReading\.type/);
  // Empty-state placeholder when the backend has not reported any
  // tools yet.
  assert.match(text, /No tools configured yet/);
  // Each per-type card is imported and dispatched on the selected
  // tool only — no ``v-for`` over the body.
  assert.doesNotMatch(text, /v-for="tool in toolStore\.tools"/);
  // The panel does not own its own polling lifecycle — the
  // base-thread store is booted once at app mount.
  assert.doesNotMatch(text, /toolStore\.start\s*\(/);
  assert.doesNotMatch(text, /toolStore\.stop\s*\(/);
});

test("SpindleCard.vue renders digital-spindle controls", () => {
  const text = read(resolve(componentsDir, "SpindleCard.vue"));
  // The file may use either the gauge-style header ("Actual<br>RPM")
  // or the older tile-style ("Actual RPM"). Both shapes render the
  // RPM telemetry; assert the substring either way.
  assert.match(
    text,
    /Actual\s*(?:<br\s*\/?\s*>\s*)?RPM/i,
    "SpindleCard must surface the actual RPM reading",
  );
  assert.match(text, /Reverse/);
  assert.match(text, /stop/i);
  // Entity getters (camelCase) replace the legacy snake_case wire
  // shape.
  assert.match(text, /minRpm/);
  assert.match(text, /maxRpm/);
  // The runtime overlay fields are surfaced as a status row.
  assert.match(text, /isConnected/);
  assert.match(text, /errorCount/);
  // The master-override bypass UI is present. The label was
  // renamed from "Manual Override Mode" to "Master Override Mode"
  // when the backend gained the ``master_override`` /
  // ``master_override_enable`` fields — both the visible label and
  // the local ref names must reflect the new naming.
  assert.match(
    text,
    /Master Override Mode/,
    "SpindleCard must surface the Master Override Mode label",
  );
  assert.match(text, /masterOverride/);
  assert.match(text, /masterOverrideSpeed/);
  assert.doesNotMatch(
    text,
    /manualOverride|manualSpeed|Manual Override/,
    "SpindleCard must not regress to the old manual-override naming",
  );
  // Slider-drag debounce dispatch: the watcher fires on every
  // tick, the timer resets, and a single POST is sent after 1 s
  // of idle. The "only when running" guard uses a local
  // ``runningState`` ref so the dispatch is suppressed while the
  // spindle is idle.
  assert.match(
    text,
    /setTimeout\s*\(\s*\(\s*\)\s*=>\s*\{[\s\S]*?\}\s*,\s*1000\s*\)/,
    "SpindleCard must debounce slider drags with a 1 s setTimeout",
  );
  // The "only-when-running" guard now reads from the entity
  // (``tool.isRunning``) so the card stays in sync with the
  // backend's telemetry — no local ``runningState`` ref to drift.
  assert.match(
    text,
    /tool\.isRunning/,
    "SpindleCard must read tool.isRunning from the entity for the only-when-running guard",
  );
  // The dispatched action comes from the entity's direction so
  // the slider watcher follows whichever direction the operator
  // last chose (Forward / Reverse).
  assert.match(text, /tool\.direction/);
  // The local ``masterOverrideSpeed`` ref is re-seeded on chip
  // switch so the slider doesn't stay at the previous spindle's
  // min_rpm when the operator clicks a different chip.
  assert.match(text, /watch\s*\(\s*\(\s*\)\s*=>\s*props\.tool\?\.id/);
  assert.match(text, /masterOverrideSpeed\.value\s*=\s*props\.tool\.minRpm/);
  // The input does NOT ``v-model`` directly onto ``props.tool`` —
  // the base-thread snapshot replaces the tool record every 1 s,
  // which would wipe the operator's typed value within a second.
  // The cards own a local ref seeded on chip switch instead.
  assert.doesNotMatch(
    text,
    /v-model(?:\.number)?="tool\.set_speed"/,
    "SpindleCard must not v-model directly onto tool.set_speed",
  );
});

test("AnalogSpindleCard.vue hides feedback tiles", () => {
  const text = read(resolve(componentsDir, "AnalogSpindleCard.vue"));
  assert.match(text, /Analog spindle/);
  assert.match(text, /Enable/);
  assert.match(text, /Disable/);
  assert.doesNotMatch(text, /Actual RPM/);
  assert.doesNotMatch(text, /Target RPM/);
  assert.doesNotMatch(text, /Reverse/);
  // Same local-ref tripwire as the digital card.
  assert.doesNotMatch(
    text,
    /v-model(?:\.number)?="tool\.set_speed"/,
    "AnalogSpindleCard must not v-model directly onto tool.set_speed",
  );
  assert.match(text, /\bsetSpeed\s*=\s*ref\(/);
  assert.match(text, /watch\s*\(\s*\(\)\s*=>\s*props\.tool\?\.id/);
});

test("HeaterControls.vue renders the shared heat block", () => {
  const text = read(resolve(componentsDir, "HeaterControls.vue"));
  assert.match(text, /Actual Temp/);
  assert.match(text, /Target Temp/);
  assert.match(text, /Set Temp/);
  // The card displays temperatures via the entity's unit-aware
  // formatters so the °C / K toggle in the temperature module
  // stays consistent.
  assert.match(text, /tool\.formatActual\(unit\)/);
  assert.match(text, /tool\.formatTarget\(unit\)/);
  // The range hint and bounds check come from the entity, not
  // from a local computed that duplicates the logic.
  assert.match(text, /tool\.boundsLabel\(unit\)/);
  assert.match(text, /tool\.hasBounds\(\)/);
  // The Set button dispatches via the entity's clamp helper so
  // the hardware bounds live in exactly one place.
  assert.match(text, /tool\.clampCelsius\(/);
  // The local ``inputTemp`` ref is re-seeded on chip switch so
  // switching tools doesn't carry the previous heater's target.
  assert.match(text, /watch\s*\(\s*\(\s*\)\s*=>\s*props\.tool\?\.id/);
});

test("HeatedBedCard.vue is a thin wrapper around HeaterControls", () => {
  const text = read(resolve(componentsDir, "HeatedBedCard.vue"));
  assert.match(text, /import HeaterControls/);
  // The bed card forwards its own entity (``tool`` IS the
  // heater) to ``HeaterControls``.
  assert.match(text, /<HeaterControls :tool="tool"/);
});

test("ExtruderCard.vue composes heat + motion in one card", () => {
  const text = read(resolve(componentsDir, "ExtruderCard.vue"));
  // Heat block via the shared component — the extruder card
  // forwards the nested heater entity (``tool.heater``), not the
  // outer ``Extruder``.
  assert.match(text, /import HeaterControls/);
  assert.match(text, /<HeaterControls :tool="tool\.heater"/);
  // Motion block — speed + retract/extrude + distance slider.
  assert.match(text, /Speed \(mm\/min\)/);
  assert.match(text, /Retract/);
  assert.match(text, /Extrude/);
  // Logarithmic distance array lives here now (moved out of the
  // panel when the per-type bodies were extracted).
  assert.match(text, /\[\s*0\.1\s*,\s*1\s*,\s*10\s*,\s*50\s*,\s*100\s*\]/);
  // Same local-ref tripwire as the spindle cards — both the
  // speed input and the distance slider bind to local refs so a
  // 1 s snapshot cannot wipe the operator's choices.
  assert.doesNotMatch(
    text,
    /v-model(?:\.number)?="tool\.set_speed"/,
    "ExtruderCard must not v-model directly onto tool.set_speed",
  );
  assert.doesNotMatch(
    text,
    /v-model(?:\.number)?="tool\.distance_index"/,
    "ExtruderCard must not v-model directly onto tool.distance_index",
  );
  assert.match(text, /\bsetSpeed\s*=\s*ref\(/);
  assert.match(text, /\bdistanceIndex\s*=\s*ref\(/);
  assert.match(text, /watch\s*\(\s*\(\)\s*=>\s*props\.tool\?\.id/);
});

test("toolStore no longer mutates the tool record", () => {
  // The base-thread snapshot replaces ``tools`` every 1 s; the
  // store must not write ``tool.target_rpm = ...`` (or any other
  // tool field) because the write would be wiped before the
  // operator sees it. The cards own their own optimistic
  // ``targetRpm`` local ref instead.
  const text = read(storePath);
  assert.doesNotMatch(
    text,
    /tool\.target_rpm\s*=/,
    "toolStore must not mutate tool.target_rpm (snapshot would wipe it)",
  );
});

test("DashboardView statically imports ToolPanel (no lazy discovery)", () => {
  // Tools module is a hard dependency. ``panelFor`` and the lazy
  // ``import.meta.glob(..., { eager: false })`` discovery pattern
  // were removed in the contract rewrite; see ``.agent/STATE.md``
  // § 13 for the no-lazy-imports rule.
  const text = read(dashboardPath);
  assert.match(
    text,
    /import\s+ToolPanelRaw\s+from\s+['"]\.\.\/modules\/tools\/components\/ToolPanel\.vue['"]/,
    "DashboardView must statically import ToolPanel from the module folder",
  );
  assert.match(text, /toolsMounted/);
  // The panel is still gated on the registry so future module
  // opt-outs (via ``MODULES_ENABLED``) continue to hide the slot.
  assert.match(text, /<ToolPanel\s+v-if="toolsMounted"/);
});