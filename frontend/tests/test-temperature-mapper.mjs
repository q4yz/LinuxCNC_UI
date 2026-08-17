// Tests for ``frontend/src/mappers/temperatureMapper.js``.
//
// The mapper is the only place that knows about the base-thread
// snapshot's heater-vs-sensor discriminator. These tests pin the
// conversion contract so a backend wire change can be fixed in
// one place.

import { test } from "node:test";
import assert from "node:assert/strict";
import { resolve, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");
const mapperPath = resolve(repoRoot, "frontend/src/mappers/temperatureMapper.js");
const mapperURL = pathToFileURL(mapperPath).href;

const {
  toReading,
  toReadingSet,
  toLegacySetTargetRequest,
  toHeaterSetTargetRequest,
} = await import(mapperURL);

test("toReading: heater wire (5 fields) → HeaterReading", () => {
  const wire = {
    tool_id: "extruder",
    actual: 210.5,
    target: 215.0,
    min_temp: 0,
    max_temp: 300,
  };
  const r = toReading(wire);
  assert.equal(r.constructor.name, "HeaterReading");
  assert.equal(r.id, "extruder");
  assert.equal(r.actualCelsius, 210.5);
  assert.equal(r.targetCelsius, 215.0);
  assert.equal(r.minTemp, 0);
  assert.equal(r.maxTemp, 300);
  assert.equal(r.isControllable, true);
  assert.equal(r.hasBounds(), true);
});

test("toReading: sensor wire (2 fields, no target) → SensorReading", () => {
  const wire = { tool_id: "chamber", actual: 32.7 };
  const r = toReading(wire);
  assert.equal(r.constructor.name, "SensorReading");
  assert.equal(r.id, "chamber");
  assert.equal(r.actualCelsius, 32.7);
  assert.equal(r.isControllable, false);
});

test("toReading: target === null → treated as sensor (discriminator)", () => {
  // Backend sends ``null`` for some standalone sensors instead of
  // omitting the key. The mapper must treat it as "no target".
  const wire = { tool_id: "ambient", actual: 24.0, target: null };
  const r = toReading(wire);
  assert.equal(r.constructor.name, "SensorReading");
});

test("toReading: missing tool_id → null", () => {
  const wire = { actual: 24.0, target: 0 };
  assert.equal(toReading(wire), null);
});

test("toReading: non-string tool_id → null", () => {
  const wire = { tool_id: 42, actual: 24.0, target: 0 };
  assert.equal(toReading(wire), null);
});

test("toReading: null / non-object input → null", () => {
  assert.equal(toReading(null), null);
  assert.equal(toReading(undefined), null);
  assert.equal(toReading("string"), null);
  assert.equal(toReading(42), null);
});

test("toReading: missing actual coerces to 0", () => {
  const wire = { tool_id: "broken", target: 0 };
  const r = toReading(wire);
  assert.equal(r.constructor.name, "HeaterReading");
  assert.equal(r.actualCelsius, 0);
});

test("toReading: heater with non-finite min_temp → null min/max", () => {
  const wire = {
    tool_id: "extruder",
    actual: 200,
    target: 210,
    min_temp: "bad",
    max_temp: NaN,
  };
  const r = toReading(wire);
  assert.equal(r.constructor.name, "HeaterReading");
  assert.equal(r.minTemp, null);
  assert.equal(r.maxTemp, null);
  assert.equal(r.hasBounds(), false);
});

test("toReadingSet: mixed dict → ReadingSet with both kinds", () => {
  const dict = {
    extruder: { tool_id: "extruder", actual: 200, target: 210, min_temp: 0, max_temp: 300 },
    bed: { tool_id: "bed", actual: 60, target: 65, min_temp: 0, max_temp: 120 },
    chamber: { tool_id: "chamber", actual: 35 },
    ambient: { tool_id: "ambient", actual: 24, target: null },
  };
  const set = toReadingSet(dict);
  assert.equal(set.size, 4);
  assert.equal(set.heaters().length, 2);
  assert.equal(set.sensors().length, 2);
  assert.ok(set.has("extruder"));
  assert.ok(set.has("chamber"));
  assert.equal(set.get("missing"), undefined);
});

test("toReadingSet: empty / null dict → empty ReadingSet", () => {
  assert.equal(toReadingSet(null).size, 0);
  assert.equal(toReadingSet(undefined).size, 0);
  assert.equal(toReadingSet({}).size, 0);
});

test("toReadingSet: malformed entries are skipped, not raised", () => {
  const dict = {
    good: { tool_id: "good", actual: 20, target: 0 },
    badNoId: { actual: 20, target: 0 },
    badNonObj: "garbage",
  };
  const set = toReadingSet(dict);
  assert.equal(set.size, 1);
  assert.ok(set.has("good"));
});

test("toLegacySetTargetRequest: builds { sensor_name, target }", () => {
  assert.deepEqual(toLegacySetTargetRequest("extruder", 210), {
    sensor_name: "extruder",
    target: 210,
  });
});

test("toHeaterSetTargetRequest: builds { tool_id, target }", () => {
  assert.deepEqual(toHeaterSetTargetRequest("extruder", 210), {
    tool_id: "extruder",
    target: 210,
  });
});
