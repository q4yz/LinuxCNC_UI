// Axis velocity / acceleration limits (mm/s, mm/s²) from the static
// base-thread tier, and the speed sliders sized from max(all axis vel).

import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const srcPath = (p: string) => resolve(here, "../src", p);
const read = (p: string) => readFileSync(srcPath(p), "utf-8");

const { toAxisState, toAxesMap } = await import(pathToFileURL(srcPath("mappers/baseThreadMapper.ts")).href);
const { createPinia, setActivePinia } = await import("pinia");
const { useBaseThreadStore } = await import(pathToFileURL(srcPath("stores/baseThread.ts")).href);

beforeEach(() => setActivePinia(createPinia()));

test("limits map from the wire onto AxisState", () => {
  const axis = toAxisState({ id: "x", joint_numbers: [0], max_velocity: 70, max_acceleration: 400 });
  assert.equal(axis.maxVelocity, 70);
  assert.equal(axis.maxAcceleration, 400);
});

test("missing, zero or garbage limits stay null — never a default", () => {
  for (const raw of [undefined, null, 0, -1, "fast"]) {
    const axis = toAxisState({ id: "x", max_velocity: raw, max_acceleration: raw });
    assert.equal(axis.maxVelocity, null, String(raw));
    assert.equal(axis.maxAcceleration, null, String(raw));
  }
});

test("maxAxisVelocity is the fastest axis, ignoring axes without a limit", () => {
  const store = useBaseThreadStore();
  assert.equal(store.maxAxisVelocity, null);

  store.axes = toAxesMap({
    x: { id: "x", max_velocity: 70 },
    z: { id: "z", max_velocity: 50 },
    a: { id: "a" }, // extruder axis: no limit
  });
  assert.equal(store.maxAxisVelocity, 70);

  store.axes = toAxesMap({ a: { id: "a" } });
  assert.equal(store.maxAxisVelocity, null);
});

test("the jog slider top is log10(max axis velocity), not a constant", () => {
  const jog = read("components/machine/JogControls.vue");
  assert.doesNotMatch(jog, /MAX_JOG_SPEED/);
  assert.match(jog, /Math\.log10\(maxAxisVelocity\.value\)/);
  assert.match(jog, /:max="maxSliderPos \?\? undefined"\s*:disabled="maxSliderPos === null"/);
});

test("the Max Speed slider top is max axis velocity in mm/min", () => {
  const speed = read("components/machine/AxisSpeedControl.vue");
  assert.doesNotMatch(speed, /max="5000"/);
  assert.match(speed, /Math\.round\(maxAxisVelocity\.value \* 60\)/);
  assert.match(speed, /:disabled="!isMachineOn \|\| maxSpeedLimit === null"/);
});
