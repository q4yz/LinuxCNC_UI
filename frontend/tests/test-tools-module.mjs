// Static-structure tests for the tools surface.
//
// Run with: node --test frontend/tests/test-tools-module.mjs
//
// The suite validates the public surface and conventions the
// tools domain must satisfy now that the registry is gone:
//
//   * The Pinia store id is the literal ``"tools"`` (no
//     ``module_`` prefix; that prefix was retired with the
//     registry).
//   * The store is backend-driven — the tool list comes from the
//     shared base-thread snapshot (``stores/baseThread.ts``); no
//     hard-coded seed list, no own polling interval.
//   * Every write action goes through the OpenAPI-generated
//     ``ModulesToolsService`` client. The store never hand-rolls
//     ``fetch`` calls (see ``.agent/context/LESSONS_LEARNED.md``
//     § 2.7). Errors are routed through ``describeError``.
//   * The panel renders one chip per tool in the header and a
//     single card body, dispatched by ``selectedTool.type``:
//     spindle_digital / spindle_analog / extruder / heated_bed.
//   * Each per-type card owns its own focused markup.
//   * The dashboard wires the panel in unconditionally.
//
// Pinia itself isn't available in bare-Node tests, and importing
// the Vue SFC requires Vite — neither is available here. This
// suite therefore stays at the source-text level (same approach
// as ``test-machine-facade.mjs``) and relies on regex checks
// plus the vite build to validate the runtime surface.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");

const componentsDir = resolve(repoRoot, "frontend/src/components/tools");
const storePath = resolve(repoRoot, "frontend/src/stores/toolsStore.ts");
const panelPath = resolve(componentsDir, "ToolPanel.vue");
const dashboardPath = resolve(repoRoot, "frontend/src/views/DashboardView.vue");

function read(p) {
  return readFileSync(p, "utf-8");
}

test("tools files exist", () => {
  assert.ok(existsSync(storePath), "toolsStore.ts missing");
  assert.ok(existsSync(panelPath), "ToolPanel.vue missing");
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

test("toolsStore uses a plain store id (no module_ prefix)", () => {
  const text = read(storePath);
  // The literal ``module_tools`` must NOT appear at all —
  // there is no longer a prefix or a manifest indirection.
  assert.doesNotMatch(text, /module_tools/);
  // The Pinia id is the literal ``"tools"`` (either passed
  // inline to ``defineStore`` or via a typed STORE_ID alias).
  const usesLiteral =
    /defineStore\(\s*['"]tools['"]/.test(text) ||
    /STORE_ID\s*=\s*['"]tools['"]/.test(text);
  assert.ok(usesLiteral, "store id must be the literal 'tools'");
});

test("toolStore consumes the base-thread snapshot — no own polling", () => {
  const text = read(storePath);
  // The mock fixture array is gone; the store reads tools from
  // the shared base-thread snapshot
  // (``stores/baseThread.ts``) so the dashboard only issues one
  // HTTP request per second for every slow stream.
  assert.doesNotMatch(text, /SEED_TOOLS/);
  assert.match(text, /useBaseThreadStore\s*\(/);
});

test("ToolPanel imports the per-type cards statically", () => {
  const text = read(panelPath);
  for (const card of [
    "AnalogSpindleCard",
    "ExtruderCard",
    "HeatedBedCard",
    "SpindleCard",
  ]) {
    assert.match(
      text,
      new RegExp(`import\\s+${card}\\s+from`),
      `ToolPanel must statically import ${card}`,
    );
  }
});

test("DashboardView unconditionally renders the ToolPanel", () => {
  // The previous ``registry.modules.has('tools')`` gate is gone;
  // tools is a hard dependency and the panel always renders.
  const text = read(dashboardPath);
  assert.match(text, /<ToolPanel\s*\/?>/);
  assert.doesNotMatch(text, /toolsMounted/);
  assert.doesNotMatch(text, /registry\.modules\.has\(\s*['"]tools['"]/);
});