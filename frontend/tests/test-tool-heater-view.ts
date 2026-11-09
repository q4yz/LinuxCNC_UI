// The Tools panel showed no values: the heater cards read the wire
// fields (tool.actual / tool.target / tool.min_temp) off the typed
// entities the store hands them (actualCelsius / targetCelsius ...,
// and an extruder's under .heater).

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import {
  clampTarget, fillFraction, formatCelsius, heaterStatus, targetFraction,
} from "../src/components/tools/heaterView";
import { toHeaterState, toExtruderState } from "../src/mappers/toolsMapper";

const src = resolve(dirname(fileURLToPath(import.meta.url)), "../src/components/tools");
const read = (f: string) => readFileSync(resolve(src, f), "utf-8");

const bed = toHeaterState({ type: "heated_bed", id: "bed", actual: 58.4, target: 60, min_temp: 0, max_temp: 120 });

test("status, bar and readout from a mapped heater", () => {
  assert.equal(heaterStatus(bed), "at-temp");
  assert.equal(heaterStatus({ ...bed, actualCelsius: 20 }), "heating");
  assert.equal(heaterStatus({ ...bed, actualCelsius: 90 }), "cooling");
  assert.equal(heaterStatus({ ...bed, targetCelsius: 0 }), "off");
  assert.equal(formatCelsius(bed.actualCelsius), "58.4");
  assert.equal(formatCelsius(undefined), "—");
  assert.ok(Math.abs(fillFraction(bed) - 58.4 / 120) < 1e-9);
  assert.equal(targetFraction(bed), 0.5);
  assert.equal(targetFraction({ ...bed, targetCelsius: 0 }), null);
});

test("set point is clamped to the heater range, 0 stays off", () => {
  assert.equal(clampTarget(500, bed), 120);
  assert.equal(clampTarget(0, bed), 0);
  assert.equal(clampTarget(Number.NaN, bed), 0);
  assert.equal(clampTarget(65, bed), 65);
});

test("an extruder's heater is what its card reads", () => {
  const e = toExtruderState({
    type: "extruder", id: "extruder", position: 0,
    heater: { type: "heater", id: "extruder", actual: 210, target: 215, min_temp: 0, max_temp: 280 },
  } as never);
  assert.equal(e.heater?.actualCelsius, 210);
  assert.match(read("ExtruderCard.vue"), /:heater="tool\.heater"/);
});

test("the cards read the typed entity, not the wire fields", () => {
  const controls = read("HeaterControls.vue");
  assert.match(controls, /heater\.actualCelsius/);
  assert.match(controls, /heater\.targetCelsius/);
  assert.doesNotMatch(controls, /tool\.(actual|target|min_temp|max_temp|set_temp)\b/);
  assert.match(read("HeatedBedCard.vue"), /:heater="tool"/);
  // The panel dispatches on the entity class and shows a live reading per tab.
  const panel = read("ToolPanel.vue");
  assert.match(panel, /instanceof Extruder/);
  assert.match(panel, /reading\(tool\)/);
});
