// The ACE Pro card: a page panel, the facade / composable behind it, and
// the rules its buttons follow.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = resolve(here, "../src");
const read = (p: string) => readFileSync(resolve(src, p), "utf-8");
const panel = read("components/filament/AcePanel.vue");

test("the ACE card is a page panel, on the Running page by default", async () => {
  const { PANEL_IDS, DEFAULT_LAYOUTS } = await import(pathToFileURL(resolve(src, "layout/pagePanels.ts")).href);
  assert.ok(PANEL_IDS.includes("ace"));
  const running = DEFAULT_LAYOUTS.running.layouts[1].columns.flat().map((i: { panel: string }) => i.panel);
  assert.ok(running.includes("ace"));
  assert.match(read("layout/panelComponents.ts"), /ace: AcePanel/);
});

test("hidden without an [ace]; a BaseCard; talks to the backend only through the facade", () => {
  assert.match(panel, /<BaseCard v-if="configured" title="ACE Pro"/);
  assert.doesNotMatch(panel, /generated\/api|fetch\(/);
  assert.match(read("composables/useAce.ts"), /aceFacade\.change\(slot\)/);
  assert.match(read("facades/aceFacade.ts"), /AceService\.aceChangeTool\(\{ slot \}\)/);
});

test("loading needs the link, an idle machine, a slot with filament and the motion permission", () => {
  assert.match(panel, /connected\.value && !changing\.value && !busy\.value && machineIdle\.value && auth\.can\("machine\.motion"\)/);
  assert.match(panel, /:disabled="!canChange \|\| !slot\.ready"/);
  // feeding and drying drive the unit only: the heaters permission
  assert.match(panel, /auth\.can\("heaters\.control"\)/);
});

test("slots are named like the slicer's tools (T0-T3) everywhere", () => {
  assert.match(panel, /T\{\{ slot\.index \}\}/);
  assert.match(panel, /return `T\$\{current\.value\}`/);
  assert.doesNotMatch(panel, /slot \{\{ n \}\}/);
});

test("a failed change shows the reason and lets the operator say what is loaded", () => {
  assert.match(panel, /v-else-if="state\?\.last_error"/);
  assert.match(panel, /ace\.setCurrent\(correction\.value\)/);
});
