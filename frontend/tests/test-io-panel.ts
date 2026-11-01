// Structural guard for the dashboard's I/O card (`.agent/component/io_pins.md`):
// a slider per fan (%) and PWM output (0 ... scale), a toggle per switched
// output, a lamp per input.
//
// Run with: ``node --test frontend/tests/test-io-panel.ts``

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const src = resolve(dirname(fileURLToPath(import.meta.url)), "../src");
const read = (rel: string) => readFileSync(resolve(src, rel), "utf-8");

test("the facade reads and sets through the machine backend's io module", () => {
  const facade = read("facades/ioFacade.ts");
  assert.match(facade, /ModulesIoService\.getIoState\(\)/);
  assert.match(facade, /ModulesIoService\.setIoValue\(id, \{ value \}\)/);
});

test("fans and PWM outputs are sliders, switched outputs toggles, inputs lamps", () => {
  const panel = read("components/io/IoPanel.vue");
  assert.match(panel, /v-for="fan in io\.fans"[\s\S]*?type="range" min="0" max="100"/, "fan: 0 ... 100 %");
  assert.match(panel, /v-if="out\.pwm"[\s\S]*?type="range" min="0" :max="out\.scale \?\? 1"/, "PWM: 0 ... scale");
  assert.match(panel, /role="switch"[\s\S]*?@click="send\(out\.id, out\.value > 0 \? 0 : 1\)"/, "switch: toggle");
  assert.match(panel, /v-for="inp in io\.inputs"/);
  // A slider is sent on release, and polling does not fight the drag.
  assert.match(panel, /@input="onDrag\(fan\.id, \$event\)"\s*@change="send\(fan\.id/);
  assert.match(panel, /dragging\.value\[id\] \?\? value/);
});

test("the card is on the dashboard behind the machine gate", () => {
  assert.match(read("views/DashboardView.vue"), /<MachineGate label="I\/O">\s*<IoPanel\/>/);
});
