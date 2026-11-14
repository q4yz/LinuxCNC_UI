// Jog controls (two-step: highlight, then jog; nothing while Running),
// the temperature chart's labels (converted once), file thumbnails (not
// draggable themselves) and the HAL scope's settings (a store, kept
// across leaving the Debug view).

import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = (p: string) => resolve(here, "../src", p);
const read = (p: string) => readFileSync(src(p), "utf8");

const { createPinia, setActivePinia } = await import("pinia");
const { useHalScopeStore } = await import(pathToFileURL(src("stores/halScopeStore.ts")).href);

beforeEach(() => setActivePinia(createPinia()));

test("jog: every button goes through pressJog, which only activates an inactive card", () => {
  const jog = read("components/machine/JogControls.vue");
  assert.equal((jog.match(/@pointerdown\.prevent="pressJog\(/g) ?? []).length, 6);
  assert.doesNotMatch(jog, /@pointerdown\.prevent="startJog\(/);
  const press = jog.slice(jog.indexOf("const pressJog"), jog.indexOf("const stopJog"));
  assert.match(press, /if \(!isActive\.value\) \{\s*focusAndActivate\(\)\s*return/);
  assert.match(press, /if \(jogBlocked\.value\)/);
});

test("jog: refused while a program runs, and a running jog stops", () => {
  const jog = read("components/machine/JogControls.vue");
  assert.match(jog, /jogBlocked = computed\(\(\) => systemState\.value === SystemState\.RUNNING\)/);
  assert.match(jog, /:disabled="jogBlocked"/);
  assert.match(jog, /watch\(jogBlocked, \(blocked\) => \{\s*if \(blocked\) void stopAllJogging\(\)/);
  const keys = jog.slice(jog.indexOf("// 4. Dispatch the Jog Command"), jog.indexOf("const handleKeyUp"));
  assert.match(keys, /if \(jogBlocked\.value\)/);
});

test("temperature chart: the data is converted once, the labels only format", () => {
  const panel = read("components/temperature/TemperaturePanel.vue");
  for (const name of ["yAxisLabelFormatter", "tooltipValueFormatter"]) {
    const start = panel.indexOf(`function ${name}`);
    const body = panel.slice(start, panel.indexOf("\n}\n", start));
    assert.doesNotMatch(body, /celsiusTo|273\.15/, `${name} converts again`);
  }
  assert.match(panel, /const round = \(v: number\) => roundTo\(celsiusTo\(v, store\.unit\), 2\)/);
});

test("file thumbnails are not dragged themselves (the row is)", () => {
  const files = read("components/FileManager.vue");
  const imgs = files.match(/<img[\s\S]*?\/>/g) ?? [];
  assert.equal(imgs.length, 2);
  for (const img of imgs) assert.match(img, /draggable="false"/);
});

test("HAL scope: settings live in one store object, kept between uses", () => {
  const first = useHalScopeStore();
  first.pins = ["motion.spindle-speed-out"];
  first.settings["motion.spindle-speed-out"] = { color: "#facc15", visible: true, scale: 5, offset: 1 };
  first.timePerDiv = 0.05;
  first.rateHz = 1000;
  first.trigger.level = 2.5;
  first.autoScaled.add("motion.spindle-speed-out");

  const again = useHalScopeStore(); // what the remounted scope gets
  assert.equal(again, first);
  assert.deepEqual(again.pins, ["motion.spindle-speed-out"]);
  assert.equal(again.settings["motion.spindle-speed-out"].scale, 5);
  assert.equal(again.timePerDiv, 0.05);
  assert.equal(again.rateHz, 1000);
  assert.equal(again.trigger.level, 2.5);
  assert.ok(again.autoScaled.has("motion.spindle-speed-out"));

  const scope = read("components/debug/scope/HalScope.vue");
  assert.match(scope, /const scope = useHalScopeStore\(\)/);
  assert.doesNotMatch(scope, /const settings = reactive|const rateHz = ref|const timePerDiv = ref/);
  assert.doesNotMatch(scope, /autoScaled\.clear\(\)/);  // a remount does not refit the channels
  assert.match(read("components/debug/HalPinStatePanel.vue"), /const \{ pins: scopePins \} = storeToRefs\(useHalScopeStore\(\)\)/);
});
