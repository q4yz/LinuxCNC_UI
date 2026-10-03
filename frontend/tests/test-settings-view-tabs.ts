// SettingsView — tabs generated from the central settings registry.
//
// Pins the contract of the generated view: one tab per registry
// category (plus the per-browser 3D Viewer tab), only the active tab is
// mounted, every row renders the setting's own editor, and the page is
// not gated on the machine backend (settings live in the system service).

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");
const viewPath = resolve(repoRoot, "frontend/src/views/SettingsView.vue");
const rowPath = resolve(repoRoot, "frontend/src/settings/components/SettingRow.vue");

const read = (p: string) => readFileSync(p, "utf-8");

test("tabs come from the registry's categories plus the 3D Viewer tab", () => {
  const text = read(viewPath);
  assert.match(text, /settingsRegistry/);
  assert.match(text, /Object\.keys\(categories\.value\)/);
  assert.match(text, /\[\.\.\.names, VIEWER_TAB\]/);
});

test("each tab button switches activeTab on click", () => {
  const text = read(viewPath);
  assert.match(text, /@click="activeTab = tab"/);
  assert.match(text, /:aria-selected="activeTab === tab"/);
});

test("only the active tab is mounted (v-if, never v-show)", () => {
  const text = read(viewPath);
  assert.match(text, /v-if="activeTab === VIEWER_TAB"/);
  assert.match(text, /v-else class="p-6 space-y-3"/);
  assert.doesNotMatch(text, /v-show=/, "v-show would mount every tab and read every critical setting");
});

test("rows render each setting's own editor — no hand-written panels", () => {
  const view = read(viewPath);
  assert.match(view, /<SettingRow v-for="setting in activeSettings"/);
  assert.doesNotMatch(view, /MachineSettingsPanel|TemperatureSettingsPanel|<CameraSettings/);
  assert.match(read(rowPath), /<component :is="setting\.component" :setting="setting" \/>/);
});

test("the page itself is not gated on the machine backend", () => {
  // Settings are served by the system service; only an editor that needs
  // machine data (the camera device list) wraps itself in MachineGate.
  assert.doesNotMatch(read(viewPath), /<MachineGate/);
});

test("critical settings are read fresh when their row mounts", () => {
  assert.match(read(rowPath), /if \(props\.setting\.critical\) void props\.setting\.load\(\)/);
});
