// Structural guard for moving the 3D viewer's render-quality toggle
// out of the viewer itself and into Settings, plus making the
// machine-limits grid optional.
//
// The toggle used to live as an overlay button inside
// NgcCoordinateSystemViewer.vue, top-right — directly under
// EStopHeader's fixed, always-on-top header (z-[100], covers the
// same corner), which made the button unreachable to clicks. Both
// controls are purely client-side localStorage preferences (no
// backend "viewer" module exists), so they now live in a dedicated
// Settings > 3D Viewer tab instead.
//
// Run with: ``node --test frontend/tests/test-viewer-settings.ts``

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");
const src = resolve(repoRoot, "frontend/src");

const read = (rel: string): string => readFileSync(resolve(src, rel), "utf-8");

const viewerPath = "components/NgcCoordinateSystemViewer.vue";
const settingsPanelPath = "components/viewer/ViewerSettingsPanel.vue";
const settingsViewPath = "views/SettingsView.vue";
const gridSettingPath = "composables/useViewerGridSetting.ts";

test("the render-quality toggle button no longer lives inside the viewer", () => {
  const text = read(viewerPath);
  assert.doesNotMatch(
    text,
    /3D: High/,
    "the unreachable overlay button (behind EStopHeader) must be removed from the viewer's own template",
  );
  assert.doesNotMatch(text, /toggleQuality/, "the viewer no longer needs the toggle function, only the read-side of the setting");
  // The viewer must still consume the setting (rendererOptions /
  // pixelRatioFor) — only the toggle UI moved, not the mechanism.
  assert.match(text, /useRenderQuality\(\)/);
  assert.match(text, /rendererOptions\(\)/);
});

test("useViewerGridSetting is a localStorage-backed singleton, defaulting to shown", () => {
  const text = read(gridSettingPath);
  assert.ok(
    text.indexOf("const showGrid") < text.indexOf("export function useViewerGridSetting"),
    "showGrid must be created outside the composable function (module-scope singleton)",
  );
  assert.match(text, /STORAGE_KEY = "linuxcnc\.viewerShowGrid"/);
  assert.match(
    text,
    /return raw === null \? true : raw !== "false"/,
    "must default to shown (true) when nothing has been stored yet",
  );
});

test("the viewer toggles the grid mesh's visibility, not its existence", () => {
  const text = read(viewerPath);
  assert.match(text, /import\s*\{\s*useViewerGridSetting\s*\}/);
  assert.match(text, /let gridMesh: THREE\.LineSegments \| null = null/);
  assert.match(
    text,
    /grid\.visible = showGrid\.value/,
    "the grid must be built either way and just hidden/shown — not conditionally constructed, so toggling doesn't need a full limits rebuild",
  );
  assert.match(
    text,
    /watch\(showGrid, \(visible\) => \{\s*if \(gridMesh\) gridMesh\.visible = visible/,
    "toggling the setting live must flip the existing mesh's visibility with no rebuild",
  );
  // The boundary outline is a separate object from the grid and must
  // not be gated by the same flag — only the grid is optional.
  assert.doesNotMatch(
    text,
    /outline\.visible = showGrid/,
    "the red boundary outline must stay visible regardless of the grid setting",
  );
});

test("ViewerSettingsPanel exposes both controls and persists via the shared composables", () => {
  const text = read(settingsPanelPath);
  assert.match(text, /import\s*\{\s*useRenderQuality\s*\}/);
  assert.match(text, /import\s*\{\s*useViewerGridSetting\s*\}/);
  assert.match(text, /@click="setQuality\('high'\)"/);
  assert.match(text, /@click="setQuality\('low'\)"/);
  assert.match(text, /@change="setShowGrid\(/);
});

test("SettingsView wires in a 3D Viewer tab, ungated by MachineGate", () => {
  const text = read(settingsViewPath);
  assert.match(text, /import ViewerSettingsPanel from '\.\.\/components\/viewer\/ViewerSettingsPanel\.vue'/);
  assert.match(text, /\{ id: 'viewer', label: '3D Viewer' \}/);
  assert.match(text, /v-else-if="activeTab === 'viewer'"/);
  // Both settings are client-side preferences with no backend module
  // to wait on — must not be wrapped in MachineGate like the other
  // three tabs are.
  const viewerTabBlock = text.match(/v-else-if="activeTab === 'viewer'"[\s\S]*?<\/div>\s*<\/div>/)?.[0] ?? "";
  assert.ok(viewerTabBlock, "expected to find the viewer tab's template block");
  assert.doesNotMatch(viewerTabBlock, /MachineGate/, "the 3D Viewer tab must not be gated behind machine-online status");
});
