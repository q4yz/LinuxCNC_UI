// Tests for ``frontend/src/mappers/progressMapper.js``.

import { test } from "node:test";
import assert from "node:assert/strict";
import { resolve, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");
const mapperURL = pathToFileURL(
  resolve(repoRoot, "frontend/src/mappers/progressMapper.js"),
).href;

const { toProgramProgress } = await import(mapperURL);
const { ProgramProgress } = await import(
  pathToFileURL(resolve(repoRoot, "frontend/src/entities/progress/ProgramProgress.js")).href
);

test("toProgramProgress: builds ProgramProgress from wire", () => {
  const p = toProgramProgress({
    current_line: 50,
    motion_line: 51,
    total_lines: 100,
    file: "demo.gcode",
    interp_state: 2,
  });
  assert.equal(p.currentLine, 50);
  assert.equal(p.motionLine, 51);
  assert.equal(p.totalLines, 100);
  assert.equal(p.file, "demo.gcode");
  assert.equal(p.interpState, 2);
  assert.equal(p.isRunning, true);
  assert.equal(p.isPaused, false);
  assert.equal(p.isLoaded, true);
  assert.equal(p.fraction, 50);
});

test("toProgramProgress: empty / null input → defaults", () => {
  const p = toProgramProgress(null);
  assert.equal(p.currentLine, 0);
  assert.equal(p.totalLines, 0);
  assert.equal(p.file, "");
  assert.equal(p.interpState, 1);
  assert.equal(p.isRunning, false);
  assert.equal(p.isLoaded, false);
  assert.equal(p.fraction, 0);
});

test("toProgramProgress: coerces non-numeric fields", () => {
  const p = toProgramProgress({
    current_line: "12",
    motion_line: null,
    total_lines: undefined,
    file: 42,
  });
  assert.equal(p.currentLine, 12);
  assert.equal(p.motionLine, 0);
  assert.equal(p.totalLines, 0);
  assert.equal(p.file, "");
});

test("ProgramProgress.fraction clamps at 100", () => {
  const p = new ProgramProgress({ currentLine: 200, totalLines: 100 });
  assert.equal(p.fraction, 100);
});

test("ProgramProgress.fraction is 0 for zero total", () => {
  const p = new ProgramProgress({ currentLine: 50, totalLines: 0 });
  assert.equal(p.fraction, 0);
});

test("ProgramProgress state predicates", () => {
  const running = new ProgramProgress({ interpState: 2 });
  const paused = new ProgramProgress({ interpState: 3 });
  const idle = new ProgramProgress({ interpState: 1 });
  const notLoaded = new ProgramProgress({ interpState: 0 });
  assert.equal(running.isRunning, true);
  assert.equal(paused.isPaused, true);
  assert.equal(idle.isIdle, true);
  assert.equal(notLoaded.isIdle, true);
});
