// Speed override entity (feed override 100 % + absolute speed cap) from
// the 1 Hz base-thread snapshot, and AxisSpeedControl bound to it.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const srcPath = (p: string) => resolve(here, "../src", p);
const read = (p: string) => readFileSync(srcPath(p), "utf-8");

const { toSpeedOverride, toSnapshot } = await import(pathToFileURL(srcPath("mappers/baseThreadMapper.ts")).href);

test("wire values map onto the entity, with slider units", () => {
  const o = toSpeedOverride({ feed_override: 1.25, max_velocity: 70 });
  assert.equal(o.feedOverride, 1.25);
  assert.equal(o.feedOverridePercent, 125);
  assert.equal(o.maxVelocity, 70);
  assert.equal(o.maxVelocityMmPerMin, 4200);
});

test("unknown values stay null — never a guessed 100 %", () => {
  for (const wire of [undefined, null, {}, { feed_override: null, max_velocity: null }]) {
    const o = toSpeedOverride(wire);
    assert.equal(o.feedOverride, null);
    assert.equal(o.feedOverridePercent, null);
    assert.equal(o.maxVelocity, null);
    assert.equal(o.maxVelocityMmPerMin, null);
  }
  assert.equal(toSnapshot({}).speedOverride.feedOverride, null);
});

test("0 % feed override (feed hold) is real; a 0 speed cap is not", () => {
  const o = toSpeedOverride({ feed_override: 0, max_velocity: 0 });
  assert.equal(o.feedOverridePercent, 0);
  assert.equal(o.maxVelocity, null);
});

test("the store refreshes speedOverride on the 1 Hz poll", () => {
  const store = read("stores/baseThread.ts");
  const refresh = store.slice(store.indexOf("async function refresh"), store.indexOf("async function fetchStaticAxes"));
  assert.match(refresh, /speedOverride\.value = snapshot\.speedOverride;/);
});

test("AxisSpeedControl shows the read-back, not local state", () => {
  const view = read("components/machine/AxisSpeedControl.vue");
  assert.match(view, /speedMultiplier = computed\(\(\) => speedOverride\.value\.feedOverridePercent\)/);
  assert.match(view, /maxSpeed = computed\(\(\) => speedOverride\.value\.maxVelocityMmPerMin\)/);
  assert.doesNotMatch(view, /ref<number \| null>\(null\)/);
  // Never invents the other value: refused while it is unknown.
  assert.match(view, /if \(multiplierPct === null \|\| limit === null\)/);
});
