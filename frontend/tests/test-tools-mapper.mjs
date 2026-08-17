// Tests for ``frontend/src/mappers/toolsMapper.js``.

import { test } from "node:test";
import assert from "node:assert/strict";
import { resolve, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");
const mapperURL = pathToFileURL(
  resolve(repoRoot, "frontend/src/mappers/toolsMapper.js"),
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

test("toSpindleState: builds SpindleState from wire", () => {
  const wire = {
    id: "spindle_main",
    type: "spindle_digital",
    state: "forward",
    actual_rpm: 12000,
    is_connected: true,
    error_count: 0,
    last_error: "",
    spindle_at_speed: true,
    min_rpm: 0,
    max_rpm: 24000,
  };
  const s = toSpindleState(wire);
  assert.equal(s.constructor.name, "SpindleState");
  assert.equal(s.id, "spindle_main");
  assert.equal(s.direction, "forward");
  assert.equal(s.actualRpm, 12000);
  assert.equal(s.isConnected, true);
  assert.equal(s.atSpeed, true);
  assert.equal(s.isRunning, true);
  assert.equal(s.fractionOfMax(), 0.5);
});

test("toSpindleState: missing actual_rpm coerces to 0", () => {
  const s = toSpindleState({ id: "x", type: "spindle_digital", state: "idle" });
  assert.equal(s.actualRpm, 0);
  assert.equal(s.isRunning, false);
});

test("toSpindleState: bogus direction falls back to idle", () => {
  const s = toSpindleState({ id: "x", type: "spindle_digital", state: "spin" });
  assert.equal(s.direction, "idle");
});

test("toExtruderState: nested heater", () => {
  const wire = {
    id: "extruder_main",
    type: "extruder",
    position: 12.5,
    heater: {
      tool_id: "extruder_main",
      actual: 210,
      target: 215,
      min_temp: 0,
      max_temp: 300,
    },
  };
  const e = toExtruderState(wire);
  assert.equal(e.constructor.name, "ExtruderState");
  assert.equal(e.id, "extruder_main");
  assert.equal(e.position, 12.5);
  assert.equal(e.heater.constructor.name, "HeaterReading");
  assert.equal(e.heater.targetCelsius, 215);
});

test("toExtruderState: flat heater fields (legacy overlay)", () => {
  const wire = {
    id: "extruder_main",
    type: "extruder",
    position: 0,
    actual_temperature: 100,
    target_temperature: 200,
    min_temp: 0,
    max_temp: 250,
  };
  const e = toExtruderState(wire);
  assert.equal(e.heater.constructor.name, "HeaterReading");
  assert.equal(e.heater.actualCelsius, 100);
  assert.equal(e.heater.targetCelsius, 200);
  assert.equal(e.heater.maxTemp, 250);
});

test("toHeaterReading: standalone heater row", () => {
  const wire = {
    id: "heater_bed",
    type: "heater",
    actual_temperature: 60,
    target_temperature: 65,
    min_temp: 0,
    max_temp: 120,
  };
  const h = toHeaterReading(wire);
  assert.equal(h.constructor.name, "HeaterReading");
  assert.equal(h.id, "heater_bed");
  assert.equal(h.actualCelsius, 60);
  assert.equal(h.targetCelsius, 65);
});

test("toHeaterReading: legacy wire uses actual/target", () => {
  const h = toHeaterReading({
    id: "x",
    type: "heater",
    actual: 50,
    target: 55,
  });
  assert.equal(h.actualCelsius, 50);
  assert.equal(h.targetCelsius, 55);
});

test("toToolState: dispatches by type discriminator", () => {
  const spindle = toToolState({
    id: "s", type: "spindle_digital", state: "idle", actual_rpm: 0,
  });
  const extruder = toToolState({
    id: "e", type: "extruder", position: 0,
    heater: { tool_id: "e", actual: 0, target: 0, min_temp: 0, max_temp: 300 },
  });
  const heater = toToolState({
    id: "h", type: "heater", actual_temperature: 0, target_temperature: 0,
  });
  assert.equal(spindle.constructor.name, "SpindleState");
  assert.equal(extruder.constructor.name, "ExtruderState");
  assert.equal(heater.constructor.name, "HeaterReading");
});

test("toToolState: unknown type / missing id → null", () => {
  assert.equal(toToolState({ id: "x", type: "mystery" }), null);
  assert.equal(toToolState({ id: "", type: "spindle_digital" }), null);
  assert.equal(toToolState(null), null);
});

test("toToolList: heterogeneous array", () => {
  const list = toToolList([
    { id: "s", type: "spindle_digital", state: "idle" },
    { id: "e", type: "extruder", heater: { tool_id: "e", actual: 0, target: 0 } },
    { id: "h", type: "heater", actual_temperature: 0, target_temperature: 0 },
    null,
  ]);
  assert.equal(list.size, 3);
  assert.equal(list.spindles().length, 1);
  assert.equal(list.extruders().length, 1);
  assert.equal(list.heaters().length, 1);
});

test("toToolList: empty / non-array input → empty ToolList", () => {
  assert.equal(toToolList(null).size, 0);
  assert.equal(toToolList(undefined).size, 0);
  assert.equal(toToolList([]).size, 0);
});

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
