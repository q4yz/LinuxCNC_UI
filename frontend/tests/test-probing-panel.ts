// Probing is a Dashboard panel (no Probing tab), its probe settings live
// in Settings -> Probing.
//
// Run with: ``node --test frontend/tests/test-probing-panel.ts``

import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { DEFAULT_LAYOUTS, PANEL_IDS } from "../src/layout/pagePanels";

const src = resolve(dirname(fileURLToPath(import.meta.url)), "../src");
const read = (rel: string) => readFileSync(resolve(src, rel), "utf-8");

test("no Probing tab: the route redirects to the dashboard, nothing in the sidebar", () => {
  assert.match(read("router/index.ts"), /path: '\/probing', redirect: \{ name: 'dashboard' \}/);
  assert.doesNotMatch(read("components/AppSidebar.vue"), /id: 'probing'/);
  assert.ok(!existsSync(resolve(src, "views/ProbingView.vue")));
});

test("a Dashboard panel, placeable like the others", () => {
  assert.ok(PANEL_IDS.includes("probe"));
  const twoColumns = DEFAULT_LAYOUTS.dashboard.layouts[1].columns[0].map((i: { panel: string }) => i.panel);
  assert.ok(twoColumns.includes("probe"));
  assert.match(read("layout/PageLayout.vue"), /probe: ProbingPanel/);
  const panel = read("components/probing/ProbingPanel.vue");
  assert.match(panel, /<BaseCard title="Probing" icon="probing" data-testid="probing-panel">/);
  assert.match(panel, /data-testid="probe-mode-toggle"/);
  assert.doesNotMatch(panel, /probe-save-settings|data-testid="x-offset"/, "no unsaved settings on the panel");
});

test("the probe settings are central settings used by every cycle", () => {
  const defs = read("settings/definitions/probing.ts");
  assert.match(defs, /new NumberSetting\(\s*"Probing",\s*"Probe tip diameter",\s*"probing\.probe_diameter"/);
  assert.match(defs, /"probing\.feedrate"/);
  assert.match(read("settings/definitions/index.ts"), /import "\.\/probing";/);
  assert.match(read("components/probing/ProbingPanel.vue"),
    /probeDiameter: Number\(probeDiameter\.value \?\? probeDiameter\.defaultValue\)/);
});
