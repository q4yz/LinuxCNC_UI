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

const {
  DEFAULT_LAYOUTS, PANEL_IDS, MIN_COLUMN_PX, addPanel, chooseLayout, minPageWidth, moveItem, normaliseLayout, removeItem,
  resizeColumn, setEnabled,
} = await load("layout/pagePanels.ts");
const { estopOverlap, ESTOP_GAP_PX } = await load("ui/estopClearance.ts");

type Item = { uid: string; panel: string };
const panels = (col: Item[]) => col.map((i) => i.panel);

test("defaults: two columns as before, one column = both in a row, three columns off", () => {
  const dash = DEFAULT_LAYOUTS.dashboard.layouts;
  assert.deepEqual(panels(dash[1].columns[0]), ["machine", "dro", "jog", "probe", "tools", "temperature", "io", "leds"]);
  assert.deepEqual(panels(dash[1].columns[1]), ["job", "console", "camera"]);
  assert.deepEqual(dash[1].widths, [4, 8]);
  assert.deepEqual(panels(dash[0].columns[0]), [...panels(dash[1].columns[0]), ...panels(dash[1].columns[1])]);
  assert.deepEqual(dash.map((l: { enabled: boolean }) => l.enabled), [true, true, false]);
  for (const page of ["dashboard", "running"]) {
    for (const [k, layout] of DEFAULT_LAYOUTS[page].layouts.entries()) {
      assert.equal(layout.columns.length, k + 1);
      assert.equal(layout.widths.reduce((a: number, b: number) => a + b, 0), 12);
    }
  }
});

test("an earlier stored layout (left / right / hidden) becomes the new one", () => {
  const out = normaliseLayout({ left: ["camera", "nope", "camera"], right: ["dro"], hidden: ["jog"] },
    DEFAULT_LAYOUTS.dashboard);
  assert.equal(out.version, 2);
  const [left, right] = out.layouts[1].columns.map(panels);
  assert.equal(left[0], "camera");
  assert.deepEqual(right.slice(0, 1), ["dro"]);
  assert.ok(![...left, ...right].includes("jog"), "hidden stays hidden");
  assert.ok(left.includes("temperature"), "a panel it did not know: where the default has it");
  assert.deepEqual(panels(out.layouts[0].columns[0]), [...left, ...right]);
  assert.equal(out.layouts[2].enabled, false);
  for (const bad of [null, 5, "x", [], {}, { left: "dro" }, { version: 2 }]) {
    assert.equal(normaliseLayout(bad, DEFAULT_LAYOUTS.running), undefined);
  }
});

test("a stored layout is cleaned", () => {
  const stored = {
    version: 2,
    layouts: [
      { enabled: false, widths: [12], columns: [[{ uid: "a", panel: "dro" }, { uid: "a", panel: "dro" }, { uid: "b", panel: "nope" }]] },
      { enabled: false, widths: [5, 5], columns: [[], ["camera"]] },
      { enabled: false, widths: [3, 6, 3], columns: [[], [], []] },
    ],
  };
  const out = normaliseLayout(stored, DEFAULT_LAYOUTS.dashboard);
  const one = out.layouts[0].columns[0];
  assert.deepEqual(panels(one), ["dro", "dro"], "the same panel twice is fine, an unknown one goes");
  assert.notEqual(one[0].uid, one[1].uid, "a repeated id is renewed");
  assert.deepEqual(out.layouts[1].widths, [4, 8], "widths not summing to 12: the default's");
  assert.deepEqual(panels(out.layouts[1].columns[1]), ["camera"]);
  assert.equal(out.layouts[0].enabled, true, "at least one layout stays on");
});

test("add (end of the first column, twice is fine), move, remove", () => {
  let v = addPanel(DEFAULT_LAYOUTS.running, 2, "camera");
  v = addPanel(v, 2, "camera");
  const first = v.layouts[1].columns[0];
  assert.deepEqual(panels(first).slice(-2), ["camera", "camera"]);
  assert.deepEqual(panels(DEFAULT_LAYOUTS.running.layouts[1].columns[0]), ["job", "axis_speed"], "untouched");
  const cam = first.at(-1).uid;
  v = moveItem(v, 2, cam, 1, 0);
  assert.equal(v.layouts[1].columns[1][0].uid, cam);
  v = moveItem(v, 2, cam, 1, 99);
  assert.equal(v.layouts[1].columns[1].at(-1).uid, cam, "an index past the end: last");
  v = removeItem(v, 2, cam);
  assert.ok(!v.layouts[1].columns.flat().some((i: Item) => i.uid === cam));
  assert.deepEqual(panels(v.layouts[1].columns[0]), ["job", "axis_speed", "camera"]);
  assert.equal(moveItem(v, 2, "nope", 0, 0), v);
});

test("column widths in twelfths: taken from the neighbour, at least one each", () => {
  const v = DEFAULT_LAYOUTS.dashboard;
  assert.deepEqual(resizeColumn(v, 2, 0, 1).layouts[1].widths, [5, 7]);
  assert.deepEqual(resizeColumn(v, 2, 1, 1).layouts[1].widths, [3, 9], "the last column takes from its left one");
  assert.deepEqual(resizeColumn(v, 3, 1, -2).layouts[2].widths, [3, 4, 5]);
  let narrow = v;
  for (let k = 0; k < 10; k++) narrow = resizeColumn(narrow, 2, 0, -1);
  assert.deepEqual(narrow.layouts[1].widths, [1, 11]);
  assert.equal(resizeColumn(v, 1, 0, 1), v);
});

test("layouts on / off: the last one on stays on", () => {
  const on = (v: { layouts: { enabled: boolean }[] }) => v.layouts.map((l) => l.enabled);
  const v = setEnabled(DEFAULT_LAYOUTS.dashboard, 1, false);
  assert.deepEqual(on(v), [false, true, false]);
  assert.equal(setEnabled(v, 2, false), v, "two columns is the last one on: refused");
  assert.deepEqual(on(setEnabled(v, 3, true)), [false, true, true]);
  assert.deepEqual(on(setEnabled(setEnabled(v, 3, true), 2, false)), [false, false, true]);
});

test("the page picks the widest enabled layout that fits, else the narrowest wraps", () => {
  let v = setEnabled(DEFAULT_LAYOUTS.dashboard, 3, true);
  const need2 = minPageWidth(v, 2), need3 = minPageWidth(v, 3);
  assert.equal(need2, Math.ceil((MIN_COLUMN_PX * 12) / 4) + 24);
  assert.equal(chooseLayout(v, need3), 3);
  assert.equal(chooseLayout(v, need3 - 1), 2);
  assert.equal(chooseLayout(v, need2 - 1), 1);
  v = setEnabled(v, 1, false);
  assert.equal(chooseLayout(v, 500), 2, "no one-column layout: two columns, which then wrap");
  v = setEnabled(setEnabled(v, 2, false), 1, true);
  assert.equal(chooseLayout(v, 5000), 3);
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
