// Page layouts (Settings -> Page layout) and the E-stop clearance of card
// headers.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = (p: string) => resolve(here, "../src", p);
const read = (p: string) => readFileSync(src(p), "utf8");
const load = (p: string) => import(pathToFileURL(src(p)).href);

const { DEFAULT_LAYOUTS, PANEL_IDS, movePanel, normaliseLayout, placementOf, shiftPanel } = await load("layout/pagePanels.ts");
const { estopOverlap, ESTOP_GAP_PX } = await load("ui/estopClearance.ts");

test("defaults: what the pages showed before, every panel placed exactly once", () => {
  assert.deepEqual(DEFAULT_LAYOUTS.dashboard.left, ["machine", "dro", "jog", "tools", "temperature", "io", "leds"]);
  assert.deepEqual(DEFAULT_LAYOUTS.dashboard.right, ["job", "console", "camera"]);
  assert.deepEqual(DEFAULT_LAYOUTS.running.left, ["job", "axis_speed"]);
  assert.deepEqual(DEFAULT_LAYOUTS.running.right, ["tools"]);
  for (const page of ["dashboard", "running"]) {
    const all = [...DEFAULT_LAYOUTS[page].left, ...DEFAULT_LAYOUTS[page].right, ...DEFAULT_LAYOUTS[page].hidden];
    assert.deepEqual([...all].sort(), [...PANEL_IDS].sort(), page);
  }
});

test("a stored layout is cleaned and a panel it does not know is placed as by default", () => {
  const stored = { left: ["camera", "nope", "camera"], right: ["dro"], hidden: ["camera", "jog"] };
  const out = normaliseLayout(stored, DEFAULT_LAYOUTS.dashboard);
  assert.deepEqual(out.left.slice(0, 1), ["camera"]);
  assert.equal(placementOf(out, "dro"), "right");
  assert.equal(placementOf(out, "jog"), "hidden");
  assert.equal(placementOf(out, "temperature"), "left"); // not stored: its default column
  const all = [...out.left, ...out.right, ...out.hidden];
  assert.equal(new Set(all).size, all.length);
  assert.deepEqual([...all].sort(), [...PANEL_IDS].sort());
  for (const bad of [null, 5, "x", [], {}, { left: "dro" }]) assert.equal(normaliseLayout(bad, DEFAULT_LAYOUTS.running), undefined);
});

test("move and shift", () => {
  const base = DEFAULT_LAYOUTS.dashboard;
  const moved = movePanel(base, "jog", "right");
  assert.equal(placementOf(moved, "jog"), "right");
  assert.equal(moved.right.at(-1), "jog");
  assert.ok(!moved.left.includes("jog"));
  assert.equal(placementOf(base, "jog"), "left"); // untouched
  const up = shiftPanel(base, "dro", -1);
  assert.deepEqual(up.left.slice(0, 2), ["dro", "machine"]);
  assert.equal(shiftPanel(base, "machine", -1), base); // already first
  assert.equal(placementOf(movePanel(base, "camera", "hidden"), "camera"), "hidden");
});

test("the pages render their layout setting; the settings page has the tab", () => {
  assert.match(read("views/DashboardView.vue"), /<PageLayout :setting="dashboardLayout" \/>/);
  assert.match(read("views/RunningView.vue"), /<PageLayout :setting="runningLayout" \/>/);
  assert.match(read("settings/definitions/index.ts"), /import "\.\/layout";/);
  const defs = read("settings/definitions/layout.ts");
  assert.match(defs, /"Page layout",\s*"Dashboard",\s*"layout\.dashboard"/);
  assert.match(defs, /"Page layout",\s*"Running",\s*"layout\.running"/);
  assert.match(read("views/SettingsView.vue"), /"Page layout"/);
});

const ESTOP = { top: 0, bottom: 112, left: 1800, right: 1920 }; // fixed, top-right

test("a row under the E-stop box right now is padded to clear it", () => {
  const header = { top: 16, bottom: 64, left: 1200, right: 1900 };
  assert.equal(estopOverlap(header, ESTOP), 1900 - 1800 + ESTOP_GAP_PX);
  // any card scrolled up beneath it, not only the top one
  assert.equal(estopOverlap({ top: 40, bottom: 88, left: 1200, right: 1900 }, ESTOP), 108);
  // the first card of a single-column (narrow) layout: full width
  assert.equal(estopOverlap({ top: 20, bottom: 80, left: 16, right: 744 }, { top: 0, bottom: 130, left: 640, right: 760 }), 744 - 640 + ESTOP_GAP_PX);
});

test("rows not under it are not: left column, below it, or scrolled out above", () => {
  assert.equal(estopOverlap({ top: 16, bottom: 64, left: 300, right: 1100 }, ESTOP), 0);
  assert.equal(estopOverlap({ top: 400, bottom: 448, left: 1200, right: 1900 }, ESTOP), 0);
  assert.equal(estopOverlap({ top: -300, bottom: -252, left: 1200, right: 1900 }, ESTOP), 0);
});

test("BaseCard shifts its header or a title-less card's first row, re-measured on scroll", () => {
  const card = read("ui/BaseCard.vue");
  assert.match(card, /ref="header"/);
  assert.match(card, /ref="body"/);
  assert.match(card, /if \(header\.value\) return header\.value;/);
  assert.match(card, /first\.offsetHeight <= MAX_ROW_PX/);
  assert.match(card, /estopOverlap\(row\.getBoundingClientRect\(\), estop\)/);
  assert.match(card, /watchEstop\(measureEstop\)/);
  const helper = read("ui/estopClearance.ts");
  assert.match(helper, /document\.addEventListener\("scroll", scheduleEstopCheck, \{ capture: true, passive: true \}\)/);
  assert.match(helper, /window\.addEventListener\("resize", scheduleEstopCheck\)/);
  assert.match(read("components/EStopHeader.vue"), /<div data-estop-overlay class="fixed top-0 right-0/);
});
