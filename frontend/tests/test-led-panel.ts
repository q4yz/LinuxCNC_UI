// Structural guard for the dashboard's LED card (`.agent/component/neopixel.md`):
// a colour picker per segment of each [neopixel] chain, "off" per chain.
//
// Run with: ``node --test frontend/tests/test-led-panel.ts``

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import { colorToHex, hexToColor } from "../src/components/io/ledColor";

const src = resolve(dirname(fileURLToPath(import.meta.url)), "../src");
const read = (rel: string) => readFileSync(resolve(src, rel), "utf-8");

test("hex <-> SET_LED channels", () => {
  assert.deepEqual(hexToColor("#ff8000"), { red: 1, green: 128 / 255, blue: 0 });
  assert.equal(colorToHex({ red: 1, green: 128 / 255, blue: 0 }), "#ff8000");
  assert.equal(colorToHex({ red: 2, green: -1, blue: 0 }), "#ff0000");
});

test("the facade reads and sets through the machine backend's leds module", () => {
  const facade = read("facades/ledsFacade.ts");
  assert.match(facade, /LedsService\.getLeds\(\)/);
  assert.match(facade, /LedsService\.setLed\(id, \{ \.\.\.color, white: 0, index: index \?\? null \}\)/);
});

test("a colour picker per segment, sent with its first LED; off per chain", () => {
  const panel = read("components/io/LedPanel.vue");
  assert.match(panel, /v-for="seg in led\.segments"[\s\S]*?type="color"[\s\S]*?@change="pick\(led\.id, seg\.first, \$event\)"/);
  assert.match(panel, /@click="off\(led\.id\)"/);
  assert.match(panel, /<BaseCard v-if="leds\.length"/, "hidden on a machine without LEDs");
});

test("the card is on the dashboard behind the machine gate", () => {
  assert.match(read("views/DashboardView.vue"), /<MachineGate label="LEDs">\s*<LedPanel\/>/);
});
