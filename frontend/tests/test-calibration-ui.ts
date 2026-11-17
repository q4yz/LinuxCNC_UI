// The Calibration tab: a card per calibration (sideways scroll), last
// tested / result / reminder / benefit / instructions / Start, the bed
// mesh's details in a pop-up, the due badge in the sidebar.
//
// Run with: ``node --test frontend/tests/test-calibration-ui.ts``

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { addDays, relativeDate, CALIBRATIONS } from "../src/config/calibrations";

const src = resolve(dirname(fileURLToPath(import.meta.url)), "../src");
const read = (rel: string) => readFileSync(resolve(src, rel), "utf-8");

test("routed and in the sidebar, with the due badge", () => {
  assert.match(read("router/index.ts"), /path: '\/calibration', name: 'calibration', component: CalibrationView/);
  const sidebar = read("components/AppSidebar.vue");
  assert.match(sidebar, /id: 'calibration', label: 'Calibration', icon: 'calibration'/);
  assert.match(sidebar, /data-testid="sidebar-calibration-due"/);
  assert.match(read("ui/Icon.vue"), /calibration: \{/);
});

test("the cards scroll sideways and snap", () => {
  const view = read("views/CalibrationView.vue");
  assert.match(view, /class="flex snap-x snap-mandatory items-stretch gap-4 overflow-x-auto pb-4"/);
  assert.match(read("components/calibration/CalibrationCard.vue"), /w-80 max-w-\[calc\(100vw-6rem\)\] shrink-0 snap-start/);
  assert.match(view, /el\.scrollBy\(\{ left: direction \* \(\(card\?\.offsetWidth \?\? 320\) \+ 16\)/);
});

test("each card: last tested, result, reminder, benefit, instructions, Start", () => {
  const card = read("components/calibration/CalibrationCard.vue");
  for (const id of ["calibration-last", "calibration-result", "calibration-reminder", "calibration-steps"]) {
    assert.match(card, new RegExp(`data-testid="${id}"`), id);
  }
  assert.match(card, /\{\{ text\.benefit \}\}/);
  assert.match(card, /:data-testid="`calibration-start-\$\{item\.id\}`"/);
  assert.match(card, /emit\("reminder", addDays\(preset\.days\)\)|emit\("reminder", addDays\(days\)\)/);
});

test("the bed mesh opens its details in a pop-up", () => {
  const view = read("views/CalibrationView.vue");
  assert.match(view, /@details="meshOpen = true"/);
  assert.match(view, /v-if="meshOpen"[\s\S]*data-testid="calibration-bed-mesh-dialog"[\s\S]*<BedMeshView \/>/);
  assert.match(read("components/calibration/CalibrationCard.vue"), /v-if="item\.kind === 'bed_mesh'"[\s\S]*@click="emit\('details'\)"/);
});

test("the probe Z offset card runs the paper test", () => {
  const card = read("components/calibration/CalibrationCard.vue");
  assert.match(card, /data-testid="calibration-paper-test"/);
  assert.match(card, /emit\('command', `TESTZ Z=\$\{dz\}`\)/);
  assert.match(card, /emit\('command', 'ACCEPT'\)/);
});

test("the facade talks to /api/v1/calibration", () => {
  const facade = read("facades/calibrationFacade.ts");
  for (const call of ["getCalibrations", "startCalibration", "setCalibrationReminder", "clearCalibration"]) {
    assert.match(facade, new RegExp(`CalibrationService\\.${call}`), call);
  }
});

test("texts for every backend kind", () => {
  for (const kind of ["bed_mesh", "z_tilt", "probe_accuracy", "probe_z_offset", "pid", "input_shaper"]) {
    assert.ok(CALIBRATIONS[kind]?.title && CALIBRATIONS[kind].benefit && CALIBRATIONS[kind].steps.length, kind);
  }
});

test("dates", () => {
  assert.equal(addDays(7, new Date(2026, 10, 17)), "2026-11-24");
  const now = new Date(2026, 10, 17, 12);
  assert.equal(relativeDate(null, now), "never");
  assert.equal(relativeDate("2026-11-17T08:00:00", now), "today");
  assert.equal(relativeDate("2026-11-16T08:00:00", now), "yesterday");
  assert.equal(relativeDate("2026-11-14T08:00:00", now), "3 days ago");
});
