// Structural guard: SettingsView's tab bar must actually switch
// panels, not just look like it does.
//
// The tab bar used to be decorative — three styled buttons with no
// click handler, no active-tab state, sitting above all three
// settings panels (Camera/Machine Config/Temperature) rendered
// simultaneously and unconditionally. CameraSettings and
// MachineSettingsPanel each fetch their own settings on mount, so
// opening this page fired three independent round-trips and mounted
// three independent component trees at once, every time the page
// opened — reported as the page feeling laggy. Only one panel should
// ever be mounted at a time now, switched via a real `activeTab` ref.
//
// Run with: ``node --test frontend/tests/test-settings-view-tabs.ts``

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");
const viewPath = resolve(repoRoot, "frontend/src/views/SettingsView.vue");

function read(): string {
  return readFileSync(viewPath, "utf-8");
}

test("SettingsView tracks which tab is active with reactive state", () => {
  const text = read();
  assert.match(text, /const activeTab = ref<SettingsTab>\('camera'\)/, "must have a reactive active-tab ref, defaulting to camera");
  assert.match(text, /type SettingsTab = 'camera' \| 'machineconfig' \| 'temperature'/);
});

test("each tab button switches activeTab on click", () => {
  const text = read();
  assert.match(
    text,
    /@click="activeTab = tab\.id"/,
    "clicking a tab button must actually change the active tab, not just look selected",
  );
  assert.match(text, /:aria-selected="activeTab === tab\.id"/, "the selected tab must be exposed to assistive tech");
});

test("only the active tab's panel is ever mounted — the other two don't exist in the DOM", () => {
  const text = read();
  // v-if / v-else-if is load-bearing here: unlike v-show, an
  // unmatched branch's component is never constructed at all, so an
  // inactive panel never fires its own onMounted settings fetch.
  assert.match(text, /v-if="activeTab === 'camera'"/);
  assert.match(text, /v-else-if="activeTab === 'machineconfig'"/);
  assert.match(text, /v-else-if="activeTab === 'temperature'"/);
  // Matches the directive itself (v-show="..."), not this test file's
  // own prose mentioning "v-show" (the source's explanatory comment
  // does exactly that, which a bare /v-show/ would false-positive on).
  assert.doesNotMatch(text, /v-show=/, "must use v-if/v-else-if, not v-show — v-show would still mount and fetch every panel");
});

test("MachineGate + panel pairing is unchanged by the tab restructuring", () => {
  const text = read();
  for (const widget of ["CameraSettings", "MachineSettingsPanel", "TemperatureSettingsPanel"]) {
    assert.match(
      text,
      new RegExp(`<MachineGate[^>]*>\\s*<${widget}[\\s/>]`),
      `<${widget}/> must still be a direct child of <MachineGate>`,
    );
  }
});
