// Print tuning on the Job status card: live Z offset, flow, excluding
// objects, the slicer's progress (``/api/v1/print-tuning``).

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const read = (p: string) => readFileSync(resolve(here, "../src", p), "utf8");

test("the facade calls the print-tuning endpoints", () => {
  const facade = read("facades/printTuningFacade.ts");
  assert.match(facade, /PrintTuningService\.getPrintTuning\(\)/);
  assert.match(facade, /setPrintTuning\(\{ z_adjust: delta \}\)/);
  assert.match(facade, /setPrintTuning\(\{ z_offset: value \}\)/);
  assert.match(facade, /setPrintTuning\(\{ flow: percent \}\)/);
  assert.match(facade, /setObjectExcluded\(index, \{ excluded \}\)/);
});

test("Z offset / flow / PA on the Tuning card, objects on the Programs card, one shared poll", () => {
  const tuning = read("components/machine/AxisSpeedControl.vue");
  assert.match(tuning, /<BaseCard title="Tuning"/);
  assert.match(tuning, /<PrintTuningControls v-if="isProgramActive" \/>/, "only while a program runs / is paused");
  const controls = read("components/print/PrintTuningControls.vue");
  assert.match(controls, /const Z_STEPS = \[0\.01, 0\.05, 0\.1, 0\.25\];/, "bigger Z steps too");
  for (const id of ["print-tuning-z", "print-tuning-flow", "print-tuning-pa"]) assert.match(controls, new RegExp(`data-testid="${id}"`));

  const card = read("components/ActivePrintWidget.vue");
  assert.doesNotMatch(card, /print-tuning-z|print-tuning-flow/, "no tuning controls on the Programs card");

  // One poll for both cards (ref-counted), stopped when neither is shown.
  const shared = read("composables/usePrintTuning.ts");
  assert.match(shared, /const POLL_MS = 2000;/);
  assert.match(shared, /if \(users === 1\)/);
  assert.match(shared, /clearInterval\(timer\)/);
});

test("Programs card: state in the header, the program's thumbnail, the slicer's estimate first", () => {
  const card = read("components/ActivePrintWidget.vue");
  assert.match(card, /<BaseCard :title="cardTitle"/);
  assert.match(card, /isPaused\.value \? "Paused" : isRunning\.value \? "Printing" : "Programs"/);
  assert.match(card, /data-testid="active-print-thumbnail"/);
  assert.match(card, /ensureThumbnail\(path\)/);
  // With the slicer's M73 progress only that is shown (percent, bar, time left).
  assert.match(card, /if \(hasSlicerProgress\.value\) \{/);
  assert.match(card, /const barPercent = computed\(\(\) => slicerPercent\.value \?\? progressFraction\.value\)/);
  assert.doesNotMatch(card, />\s*Progress\s*</, "no separate 'Progress' row");
  // [thumbnail] name + progress | objects ; [thumbnail] Start · Pause / Resume · Inspect · Stop
  const thumb = card.indexOf('data-testid="active-print-thumbnail"');
  const line = card.indexOf('data-testid="active-print-progress-line"');
  const toggle = card.indexOf('<PrintObjects v-if="isActive" v-model:open="objectsOpen" />');
  const buttons = card.indexOf('data-testid="active-print-buttons"');
  assert.ok(thumb > 0 && thumb < line && line < toggle && toggle < buttons, "thumbnail, progress, objects, buttons");
  assert.match(card, /class="row-span-2/, "the thumbnail spans both rows");
  assert.match(card, /<BaseButton v-if="isLoaded" size="sm" variant="success" class="w-24" @click="startLoadedProgram">Start<\/BaseButton>/);
  assert.doesNotMatch(card, /#header-actions/, "Start is in the button row, not the header");
  // Objects: a sub-menu — a toggle in the progress row, its list below.
  assert.match(read("components/print/PrintObjects.vue"), /defineModel<boolean>\("open"/);
  assert.match(card, /<PrintObjectList v-if="objectsOpen" \/>/);
  assert.match(read("components/print/PrintObjectList.vue"), /exclude\(object\.index, !object\.excluded\)/);
});

test("console suggestions for the new commands", () => {
  const gcodes = read("config/gcodes.ts");
  for (const label of ["M221", "M600", "SET_GCODE_OFFSET"]) assert.match(gcodes, new RegExp(`label: '${label}'`));
});
