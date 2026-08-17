// Tests for ``frontend/src/mappers/temperatureMapper.ts``.
//
// The backend now sends a ``type`` field on every sensors-dict
// entry — the mapper dispatches on it directly.

import { test } from "node:test";
import assert from "node:assert/strict";
import { resolve, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");
const mapperURL = pathToFileURL(
  resolve(repoRoot, "frontend/src/mappers/temperatureMapper.ts"),
).href;

const {
  toReading,
  toReadingSet,
  toLegacySetTargetRequest,
  toHeaterSetTargetRequest,
} = await import(mapperURL);

// ---------------------------------------------------------------------------
// Live wire fixtures — copied from the live backend's response models.
// ---------------------------------------------------------------------------

function heaterWire(overrides = {}) {
  return {
    type: "heater",
    tool_id: "extruder",
    target: 215,
    actual: 210,
    min_temp: 0,
    max_temp: 300,
    ...overrides,
  };
}

function sensorWire(overrides = {}) {
  return {
    type: "sensor",
    tool_id: "chamber",
    actual: 32.7,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// toReading — type-driven dispatcher
// ---------------------------------------------------------------------------

test("toReading: type='heater' → HeaterReading", () => {
  const r = toReading(heaterWire());
  assert.equal(r.constructor.name, "HeaterReading");
  assert.equal(r.id, "extruder");
  assert.equal(r.actualCelsius, 210);
  assert.equal(r.targetCelsius, 215);
  assert.equal(r.minTemp, 0);
  assert.equal(r.maxTemp, 300);
});

test("toReading: type='sensor' → SensorReading", () => {
  const r = toReading(sensorWire());
  assert.equal(r.constructor.name, "SensorReading");
  assert.equal(r.id, "chamber");
  assert.equal(r.actualCelsius, 32.7);
});

test("toReading: missing tool_id → null", () => {
  assert.equal(toReading({ type: "heater" }), null);
  assert.equal(toReading({ type: "sensor" }), null);
});

test("toReading: null / non-object input → null", () => {
  assert.equal(toReading(null), null);
  assert.equal(toReading(undefined), null);
  assert.equal(toReading("string"), null);
  assert.equal(toReading(42), null);
});

test("toReading: missing actual coerces to 0", () => {
  const r = toReading({ type: "sensor", tool_id: "x" });
  assert.equal(r.constructor.name, "SensorReading");
  assert.equal(r.actualCelsius, 0);
});

test("toReading: heater with non-finite min_temp / max_temp → null", () => {
  const r = toReading({
    type: "heater",
    tool_id: "x",
    target: 0,
    actual: 0,
    min_temp: "bad",
    max_temp: NaN,
  });
  assert.equal(r.constructor.name, "HeaterReading");
  assert.equal(r.minTemp, null);
  assert.equal(r.maxTemp, null);
  assert.equal(r.hasBounds(), false);
});

test("toReading: unknown / missing type → null", () => {
  assert.equal(toReading({ tool_id: "x" }), null);
  assert.equal(toReading({ tool_id: "x", type: "mystery" }), null);
});

test("toReading: type='spindle_digital' is NOT a temperature reading", () => {
  // Spindles live in the tools[] array; the sensors dict never
  // carries spindle rows. The mapper correctly rejects them.
  assert.equal(
    toReading({ type: "spindle_digital", id: "spindle_main" }),
    null,
  );
});

// ---------------------------------------------------------------------------
// toReadingSet
// ---------------------------------------------------------------------------

test("toReadingSet: mixed dict → ReadingSet with both kinds", () => {
  const dict = {
    extruder: heaterWire({ tool_id: "extruder" }),
    bed: heaterWire({ tool_id: "bed" }),
    chamber: sensorWire({ tool_id: "chamber" }),
    ambient: sensorWire({ tool_id: "ambient" }),
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
    good: heaterWire({ tool_id: "extruder" }),
    badNoId: { type: "heater", target: 0, actual: 0 },
    badNonObj: "garbage",
  };
  const set = toReadingSet(dict);
  assert.equal(set.size, 1);
  assert.ok(set.has("extruder"));
});

// ---------------------------------------------------------------------------
// Write-side wire helpers
// ---------------------------------------------------------------------------

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
