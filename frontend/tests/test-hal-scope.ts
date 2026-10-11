// HAL oscilloscope core: sample buffer, trigger search, window placement,
// scaling helpers, and the debug panel wiring.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = (p: string) => resolve(here, "../src", p);
const load = (p: string) => import(pathToFileURL(src(p)).href);

const { ScopeBuffer, lowerBound } = await load("components/debug/scope/ScopeBuffer.ts");
const { findTrigger, placeWindow, niceStep, stepScale, autoScale, formatTime } = await load(
  "components/debug/scope/scopeMath.ts",
);
const { scopeSocketUrl } = await load("components/debug/scope/useHalScopeStream.ts");

/** n samples at `rate` Hz of fn(t), starting at t0. */
function frame(pins: string[], fns: ((t: number) => number | null)[], t0: number, n: number, rate = 100) {
  const t = Array.from({ length: n }, (_, i) => t0 + i / rate);
  return { pins, t, v: fns.map((fn) => t.map(fn)) };
}

const square = (t: number) => ((t % 1) < 0.5 ? 1 : 0); // rises at t = 0, 1, 2, …

test("buffer appends frames per pin and resets on a new pin set", () => {
  const buffer = new ScopeBuffer(60);
  buffer.append(frame(["a", "b"], [() => 1, () => 2], 0, 5));
  buffer.append(frame(["a", "b"], [() => 3, () => 4], 0.05, 5));
  assert.equal(buffer.length, 10);
  assert.deepEqual(buffer.values("a").slice(4, 6), [1, 3]);
  assert.deepEqual(buffer.values("b").slice(-1), [4]);

  buffer.append(frame(["c"], [() => 9], 0, 3));
  assert.deepEqual(buffer.pins, ["c"]);
  assert.equal(buffer.length, 3);
});

test("buffer keeps only the last maxSeconds and restarts on a restarted clock", () => {
  const buffer = new ScopeBuffer(1);
  buffer.append(frame(["a"], [() => 0], 0, 1000, 100)); // 10 s
  assert.ok(buffer.times[0] >= 9 - 0.02, `oldest kept ${buffer.times[0]}`);
  assert.ok(Math.abs(buffer.effectiveRate() - 100) < 1);

  buffer.append(frame(["a"], [() => 1], 0, 5)); // sampler restarted at t≈0
  assert.equal(buffer.length, 5);
});

test("lowerBound", () => {
  assert.equal(lowerBound([0, 1, 2, 3], 1.5), 2);
  assert.equal(lowerBound([0, 1, 2, 3], -1), 0);
  assert.equal(lowerBound([0, 1, 2, 3], 9), 4);
});

test("trigger finds the latest rising / falling crossing, interpolated", () => {
  const { t, v } = frame(["s"], [square], 0, 300); // 3 s
  const rising = findTrigger(t, v[0], "rising", 0.5, 2.9);
  assert.ok(Math.abs(rising! - 2.0) < 0.011, `rising at ${rising}`);
  const falling = findTrigger(t, v[0], "falling", 0.5, 2.9);
  assert.ok(Math.abs(falling! - 2.5) < 0.011, `falling at ${falling}`);
  assert.equal(findTrigger(t, v[0], "rising", 5, 2.9), null, "level never crossed");

  const ramp = frame(["r"], [(x) => x], 0, 100);
  const at = findTrigger(ramp.t, ramp.v[0], "rising", 0.505, 1);
  assert.ok(Math.abs(at! - 0.505) < 1e-9, "linear interpolation between samples");
});

test("a gap (null) never counts as a crossing", () => {
  const times = [0, 0.01, 0.02, 0.03];
  assert.equal(findTrigger(times, [0, null, 1, 1], "rising", 0.5, 1), null);
});

test("window: triggered picture with the trigger at the chosen position", () => {
  const { t, v } = frame(["s"], [square], 0, 300);
  const opts = { span: 0.4, position: 0.25, mode: "auto" as const, edge: "rising" as const, level: 0.5 };
  const w = placeWindow(t, v[0], opts, null)!;
  assert.ok(w.triggerAt !== null && Math.abs(w.triggerAt - 2) < 0.011);
  assert.ok(Math.abs(w.start - (w.triggerAt! - 0.1)) < 1e-9);
  assert.ok(Math.abs(w.end - (w.triggerAt! + 0.3)) < 1e-9);
});

test("window: off rolls, auto rolls without a trigger, normal holds", () => {
  const flat = frame(["s"], [() => 0], 0, 300);
  const base = { span: 1, position: 0.5, edge: "rising" as const, level: 0.5 };
  const roll = placeWindow(flat.t, flat.v[0], { ...base, mode: "off" }, null)!;
  assert.equal(roll.triggerAt, null);
  assert.ok(Math.abs(roll.end - flat.t[flat.t.length - 1]) < 1e-9);

  assert.equal(placeWindow(flat.t, flat.v[0], { ...base, mode: "auto" }, null)!.triggerAt, null);

  const held = { start: 0, end: 1, triggerAt: 0.5 };
  assert.equal(placeWindow(flat.t, flat.v[0], { ...base, mode: "normal" }, held), held);
  assert.equal(placeWindow(flat.t, flat.v[0], { ...base, mode: "normal" }, null), null, "WAIT until the first trigger");
});

test("1-2-5 scale steps and auto-scale", () => {
  assert.equal(niceStep(0.3), 0.5);
  assert.equal(niceStep(7), 10);
  assert.deepEqual([1, 2, 5, 10].map((x) => stepScale(x, 1)), [2, 5, 10, 20]);
  assert.deepEqual([1, 2, 5, 10].map((x) => stepScale(x, -1)), [0.5, 1, 2, 5]);
  assert.equal(stepScale(0.001, 1), 0.002);

  const fit = autoScale([-50, 0, 50, null]);
  assert.ok(fit && fit.scale >= 100 / 6 && fit.scale <= 20);
  assert.equal(fit!.offset, 0);
  assert.equal(autoScale([1000, 1300])!.offset, -23);
  const bit = autoScale([0, 1, 1, 0])!;
  assert.ok(bit.scale > 0);
  assert.equal(autoScale([null, null]), null);
  assert.equal(formatTime(0.002), "2 ms");
  assert.equal(formatTime(2), "2 s");
});

test("socket URL follows the page protocol and host (proxied like /ws/telemetry)", () => {
  assert.equal(scopeSocketUrl({ protocol: "https:", host: "10.0.0.5" }), "wss://10.0.0.5/ws/hal-scope");
  assert.equal(scopeSocketUrl({ protocol: "http:", host: "localhost:5180" }), "ws://localhost:5180/ws/hal-scope");
});

test("debug panel: live 1 Hz poll while visible, ∿ toggles on every pin, scope mounted", () => {
  const panel = readFileSync(src("components/debug/HalPinStatePanel.vue"), "utf-8");
  assert.match(panel, /POLL_MS = 1000/);
  assert.match(panel, /IntersectionObserver/);
  assert.match(panel, /visibilitychange/);
  assert.match(panel, /readPinValues\(ids\)/, "only the pins on screen are read");
  assert.match(panel, /<HalScope v-model="scopePins" \/>/);
  assert.match(panel, /:scope-ids="scopeIds"/);

  const row = readFileSync(src("views/hal-visual-editor/PinTreeItem.vue"), "utf-8");
  assert.match(row, /v-if="scopeIds"/, "the toggle only appears where the scope is offered");
  assert.match(row, /data-test="`hal-pin-scope-\$\{node\.pin\.id\}`"/);
});
