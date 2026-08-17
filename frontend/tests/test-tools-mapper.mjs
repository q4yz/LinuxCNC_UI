// Tests for ``frontend/src/mappers/toolsMapper.ts``.
//
// The backend now sends a ``type`` field on every tool row — the
// mapper dispatches on it directly. The wire field names map to
// entity getters per the OOP layer (``min_rpm`` → ``minRpm``, etc.).

import { test } from "node:test";
import assert from "node:assert/strict";
import { resolve, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");
const mapperURL = pathToFileURL(
  resolve(repoRoot, "frontend/src/mappers/toolsMapper.ts"),
).href;

const {
  toToolState,
  toToolList,
  toSpindleState,
  toExtruderState,
  toHeaterReading,
  toSpindleCommand,
  toExtruderCommand,
  toHeaterCommand,
} = await import(mapperURL);

// ---------------------------------------------------------------------------
// Live wire fixtures — copied from the live backend's response models.
// ---------------------------------------------------------------------------

function spindleWireDigital(overrides = {}) {
  return {
    type: "spindle_digital",
    id: "spindle_main",
    target_rpm: 12000,
    actual_rpm: 11500,
    is_connected: true,
    error_count: 0,
    last_error: "",
    spindle_at_speed: true,
    min_rpm: 0,
    max_rpm: 24000,
    state: "forward",
    ...overrides,
  };
}

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

function extruderWire(overrides = {}) {
  return {
    type: "extruder",
    id: "extruder_main",
    position: 12.5,
    heater: {
      type: "heater",
      tool_id: "extruder_main",
      target: 215,
      actual: 210,
      min_temp: 0,
      max_temp: 300,
    },
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// toSpindleState — SpindleDigitalStateResponse
// ---------------------------------------------------------------------------

test("toSpindleState: type='spindle_digital' → SpindleDigital", () => {
  const s = toSpindleState(spindleWireDigital());
  assert.equal(s.constructor.name, "SpindleDigital");
  assert.equal(s.id, "spindle_main");
  assert.equal(s.direction, "forward");
  assert.equal(s.actualRpm, 11500);
  assert.equal(s.isConnected, true);
  assert.equal(s.errorCount, 0);
  assert.equal(s.atSpeed, true);
  assert.equal(s.isRunning, true);
  assert.equal(s.fractionOfMax(), 11500 / 24000);
});

test("toSpindleState: missing actual_rpm coerces to 0", () => {
  const s = toSpindleState({
    type: "spindle_digital",
    id: "x",
    state: "idle",
    min_rpm: 0,
    max_rpm: 24000,
  });
  assert.equal(s.actualRpm, 0);
  assert.equal(s.isRunning, false);
});

test("toSpindleState: bogus direction falls back to idle", () => {
  const s = toSpindleState({ type: "spindle_digital", id: "x", state: "spin" });
  assert.equal(s.direction, "idle");
});

test("toSpindleState: backward direction is detected", () => {
  const s = toSpindleState({ type: "spindle_digital", id: "x", state: "backward" });
  assert.equal(s.direction, "backward");
  assert.equal(s.isRunning, true);
});

// ---------------------------------------------------------------------------
// toExtruderState — ExtruderStateResponse with nested heater
// ---------------------------------------------------------------------------

test("toExtruderState: type='extruder' → Extruder", () => {
  const e = toExtruderState(extruderWire());
  assert.equal(e.constructor.name, "Extruder");
  assert.equal(e.id, "extruder_main");
  assert.equal(e.position, 12.5);
  assert.equal(e.heater.constructor.name, "HeaterReading");
  assert.equal(e.heater.id, "extruder_main");
  assert.equal(e.heater.actualCelsius, 210);
  assert.equal(e.heater.targetCelsius, 215);
  assert.equal(e.heater.maxTemp, 300);
});

test("toExtruderState: missing heater object → null heater", () => {
  const e = toExtruderState({ type: "extruder", id: "x", position: 0 });
  assert.equal(e.constructor.name, "Extruder");
  assert.equal(e.heater, null);
});

test("toExtruderState: nested heater with no tool_id falls back to outer id", () => {
  const e = toExtruderState({
    type: "extruder",
    id: "extruder_main",
    position: 0,
    heater: {
      type: "heater",
      target: 200,
      actual: 100,
      min_temp: 0,
      max_temp: 250,
    },
  });
  assert.equal(e.constructor.name, "Extruder");
  assert.equal(e.heater.id, "extruder_main");
});

// ---------------------------------------------------------------------------
// toHeaterReading — HeaterStateResponse
// ---------------------------------------------------------------------------

test("toHeaterReading: type='heater' → HeaterReading", () => {
  const h = toHeaterReading(heaterWire());
  assert.equal(h.constructor.name, "HeaterReading");
  assert.equal(h.id, "extruder");
  assert.equal(h.actualCelsius, 210);
  assert.equal(h.targetCelsius, 215);
  assert.equal(h.minTemp, 0);
  assert.equal(h.maxTemp, 300);
});

test("toHeaterReading: type='heated_bed' (legacy alias) → HeaterReading", () => {
  const h = toHeaterReading({ ...heaterWire(), type: "heated_bed" });
  assert.equal(h.constructor.name, "HeaterReading");
});

test("toHeaterReading: non-finite min/max → null", () => {
  const h = toHeaterReading({
    type: "heater",
    tool_id: "x",
    target: 0,
    actual: 0,
    min_temp: "bad",
    max_temp: NaN,
  });
  assert.equal(h.minTemp, null);
  assert.equal(h.maxTemp, null);
  assert.equal(h.hasBounds(), false);
});

// ---------------------------------------------------------------------------
// toToolState — type-driven dispatcher
// ---------------------------------------------------------------------------

test("toToolState: type='spindle_digital' → SpindleDigital", () => {
  const s = toToolState(spindleWireDigital());
  assert.equal(s.constructor.name, "SpindleDigital");
  assert.equal(s.id, "spindle_main");
});

test("toToolState: type='spindle_analog' → SpindleDigital", () => {
  const s = toToolState({ ...spindleWireDigital(), type: "spindle_analog" });
  assert.equal(s.constructor.name, "SpindleDigital");
});

test("toToolState: type='extruder' → Extruder", () => {
  const e = toToolState(extruderWire());
  assert.equal(e.constructor.name, "Extruder");
  assert.equal(e.id, "extruder_main");
});

test("toToolState: type='heater' → HeaterReading", () => {
  const h = toToolState(heaterWire());
  assert.equal(h.constructor.name, "HeaterReading");
  assert.equal(h.id, "extruder");
});

test("toToolState: type='heated_bed' (legacy alias) → HeaterReading", () => {
  const h = toToolState({ ...heaterWire(), type: "heated_bed" });
  assert.equal(h.constructor.name, "HeaterReading");
});

test("toToolState: unknown / missing type → null", () => {
  assert.equal(toToolState({ id: "x" }), null);
  assert.equal(toToolState({ id: "x", type: "mystery" }), null);
  assert.equal(toToolState(null), null);
});

test("toToolState: missing id / tool_id → null", () => {
  assert.equal(toToolState({ type: "spindle_digital" }), null);
  assert.equal(toToolState({ type: "heater" }), null);
  assert.equal(toToolState({ type: "extruder" }), null);
});

test("toToolState: heterogeneous live tools[] array dispatches correctly", () => {
  const arr = [
    spindleWireDigital({ id: "spindle_main", type: "spindle_digital" }),
    heaterWire({ tool_id: "extruder", type: "heater" }),
    extruderWire({ id: "extruder_main", type: "extruder" }),
    heaterWire({ tool_id: "bed", type: "heater" }),
  ];
  const out = arr.map(toToolState).filter((t) => t !== null);
  assert.equal(out.length, 4);
  assert.equal(
    out.filter((t) => t.constructor.name === "SpindleDigital").length,
    1,
  );
  assert.equal(
    out.filter((t) => t.constructor.name === "HeaterReading").length,
    2,
  );
  assert.equal(
    out.filter((t) => t.constructor.name === "Extruder").length,
    1,
  );
});

// ---------------------------------------------------------------------------
// toToolList
// ---------------------------------------------------------------------------

test("toToolList: heterogeneous live-wire array → ToolList", () => {
  const list = toToolList([
    spindleWireDigital({ id: "spindle_main" }),
    heaterWire({ tool_id: "extruder" }),
    extruderWire({ id: "extruder_main" }),
    { type: "mystery", id: "x" },
    null,
  ]);
  assert.equal(list.size, 3);
  assert.equal(list.spindles().length, 1);
  assert.equal(list.extruders().length, 1);
  assert.equal(list.heaters().length, 1);
  assert.equal(list.get("spindle_main").actualRpm, 11500);
  assert.equal(list.get("extruder").targetCelsius, 215);
  assert.equal(list.get("extruder_main").heater.id, "extruder_main");
});

test("toToolList: empty / non-array input → empty ToolList", () => {
  assert.equal(toToolList(null).size, 0);
  assert.equal(toToolList(undefined).size, 0);
  assert.equal(toToolList([]).size, 0);
});

test("toToolList: malformed entries are skipped, not raised", () => {
  const list = toToolList([
    { type: "spindle_digital", id: "good" },
    { type: "mystery", id: "bad" },
  ]);
  assert.equal(list.size, 1);
  assert.ok(list.has("good"));
});

// ---------------------------------------------------------------------------
// Write-side wire-shape helpers (unchanged).
// ---------------------------------------------------------------------------

test("toSpindleCommand: defaults", () => {
  assert.deepEqual(toSpindleCommand({ toolId: "s", action: "stop", speed: 0 }), {
    tool_id: "s",
    action: "stop",
    speed: 0,
    master_override: 0,
    master_override_enable: false,
    override: 1.0,
  });
});

test("toExtruderCommand: defaults heater_action to set", () => {
  assert.deepEqual(
    toExtruderCommand({
      toolId: "e",
      action: "extrude",
      distance: 5,
      speed: 300,
      heaterTarget: 200,
    }),
    {
      tool_id: "e",
      action: "extrude",
      distance: 5,
      speed: 300,
      heater: { tool_id: "e", target: 200 },
      heater_action: "set",
    },
  );
});

test("toHeaterCommand: minimal shape", () => {
  assert.deepEqual(toHeaterCommand({ toolId: "h", target: 210 }), {
    tool_id: "h",
    target: 210,
  });
});
