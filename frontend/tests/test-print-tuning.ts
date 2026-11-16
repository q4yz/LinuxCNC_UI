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

test("the card shows it while a print runs, polling", () => {
  const card = read("components/ActivePrintWidget.vue");
  assert.match(card, /import PrintTuning from "\.\/print\/PrintTuning\.vue";/);
  assert.match(card, /<PrintTuning \/>/);
  const panel = read("components/print/PrintTuning.vue");
  assert.match(panel, /const POLL_MS = 2000;/);
  assert.match(panel, /const Z_STEPS = \[-0\.05, -0\.01, 0\.01, 0\.05\];/);
  assert.match(panel, /clearInterval\(timer\)/);
  assert.match(panel, /toggleObject\(object\.index, !object\.excluded\)/);
  assert.match(panel, /data-testid="print-tuning-slicer"/);
});

test("console suggestions for the new commands", () => {
  const gcodes = read("config/gcodes.ts");
  for (const label of ["M221", "M600", "SET_GCODE_OFFSET"]) assert.match(gcodes, new RegExp(`label: '${label}'`));
});
