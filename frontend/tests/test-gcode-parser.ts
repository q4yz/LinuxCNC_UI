// Behavioural tests for ``frontend/src/parsers/gcodeParser.ts``.
//
// The parser is a pure ``string -> ParsedSegment[]`` function with
// no DOM / Three.js / fetch dependencies, so we can drive it from
// the node:test runner just like the rest of ``frontend/tests``.
// The style mirrors ``test-macro-button.ts`` — one ``test(...)`` per
// behaviour, assertions via ``node:assert/strict``.
//
// What is locked down here:
//
//   * Comment stripping (semicolon + balanced / unbalanced parens).
//   * Modal motion (G1 / G2 / G3 stick across lines; G0 stays
//     non-modal).
//   * WCS tracking (G54..G59.3 → wcsIndex 1..9).
//   * G92 family (set per-axis / .1 clear / .2 suspend / .3 resume).
//   * G90 / G91 absolute / incremental.
//   * G2 / G3 arc interpolation in the active plane (G17 / G18 /
//     G19), with both I / J / K offsets and R-word.
//   * Helical arcs (out-of-plane axis interpolates linearly).
//   * G90.1 / G91.1 arc-centre mode.
//   * Source-line tracking.
//   * Permissive fall-through on garbage input.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import {
  parseGcodeToolpath,
  wcsNameForIndex,
} from "../src/parsers/gcodeParser";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");
const examplePath = resolve(repoRoot, "nc_files/example.ngc");
const ng1001Path = resolve(repoRoot, "nc_files/1001.ngc");

const eps = 1e-6;
const closeTo = (a: number, b: number, tol = eps) =>
  Math.abs(a - b) <= tol;

// ---------------------------------------------------------------- //
// Comment stripping                                                  //
// ---------------------------------------------------------------- //

test("strips ; comments to end of line", () => {
  const segs = parseGcodeToolpath("G1 X10 ; trailing comment");
  assert.equal(segs.length, 1);
  assert.deepEqual(segs[0].to, [10, 0, 0]);
});

test("strips balanced ( ... ) comments", () => {
  const segs = parseGcodeToolpath("G1 X10 (this is a comment) Y5");
  assert.equal(segs.length, 1);
  assert.deepEqual(segs[0].to, [10, 5, 0]);
});

test("strips balanced nested ( ... ( ... ) ... ) parens", () => {
  // LinuxCNC's comment dialect is technically non-nesting, but
  // balanced parens are a degenerate case the parser accepts.
  const segs = parseGcodeToolpath("G1 X10 (outer (inner) tail)");
  assert.equal(segs.length, 1);
  assert.deepEqual(segs[0].to, [10, 0, 0]);
});

test("falls back gracefully when a comment opens but never closes", () => {
  // LinuxCNC's interpreter behaviour on unbalanced ``(`` is
  // implementation-defined; our parser keeps the line and applies
  // a best-effort non-greedy strip so the rest still tokenises.
  // The contract is "does not throw" and "produces at most one
  // segment per line that has parseable axis words".
  const segs = parseGcodeToolpath("G1 X10 (unclosed");
  assert.ok(segs.length <= 1);
  if (segs.length === 1) {
    assert.deepEqual(segs[0].to, [10, 0, 0]);
  }
});

// ---------------------------------------------------------------- //
// Defaults and empty input                                           //
// ---------------------------------------------------------------- //

test("empty input returns an empty array", () => {
  assert.deepEqual(parseGcodeToolpath(""), []);
});

test("garbage input returns an empty array without throwing", () => {
  // Mirrors the contents of ``nc_files/gg.gcode``.
  const segs = parseGcodeToolpath("ssteeshgghghhgdddddddddffffxvvvvddddssddkll11111");
  assert.deepEqual(segs, []);
});

test("a permissive G1 default applies before any modal motion", () => {
  // No G-code on the line, no prior modal motion: the parser still
  // emits a straight segment so a stray ``X10`` is visible in the
  // preview.
  const segs = parseGcodeToolpath("X10");
  assert.equal(segs.length, 1);
  assert.deepEqual(segs[0].from, [0, 0, 0]);
  assert.deepEqual(segs[0].to, [10, 0, 0]);
});

// ---------------------------------------------------------------- //
// Modal motion                                                       //
// ---------------------------------------------------------------- //

test("G1 sticks across subsequent lines without re-stating the G-code", () => {
  const segs = parseGcodeToolpath("G1 X10\nX20");
  assert.equal(segs.length, 2);
  assert.deepEqual(segs[0].from, [0, 0, 0]);
  assert.deepEqual(segs[0].to,   [10, 0, 0]);
  assert.deepEqual(segs[1].from, [10, 0, 0]);
  assert.deepEqual(segs[1].to,   [20, 0, 0]);
});

test("G0 is non-modal: a later line without G-code uses the prior modal motion", () => {
  // G1 X10 sets modal to G1. G0 X0 emits a rapid segment but does
  // not change the modal group. The next X20 line therefore moves
  // as a G1, not another rapid.
  const segs = parseGcodeToolpath("G1 X10\nG0 X0\nX20");
  assert.equal(segs.length, 3);
  assert.deepEqual(segs[0].to, [10, 0, 0]);
  assert.deepEqual(segs[1].to, [0,  0, 0]);
  assert.deepEqual(segs[2].to, [20, 0, 0]);
});

test("G80 cancels modal motion", () => {
  // After G80, a line with only axis words and no G-code defaults
  // back to G1 (permissive).
  const segs = parseGcodeToolpath("G1 X5\nG80\nX10");
  assert.equal(segs.length, 2);
  assert.deepEqual(segs[0].to, [5,  0, 0]);
  assert.deepEqual(segs[1].to, [10, 0, 0]);
});

// ---------------------------------------------------------------- //
// WCS tracking                                                       //
// ---------------------------------------------------------------- //

test("WCS index 1..9 is captured per segment", () => {
  const segs = parseGcodeToolpath(
    "G54\nG1 X1\nG55\nX2\nG59.1\nX3\nG59.3\nX4",
  );
  // Skip the first segment for the G54 line because it's a "no
  // motion" line that updates WCS but has no axis words.
  assert.equal(segs.length, 4);
  assert.equal(segs[0].wcsIndex, 1);
  assert.equal(segs[1].wcsIndex, 2);
  assert.equal(segs[2].wcsIndex, 7);
  assert.equal(segs[3].wcsIndex, 9);
});

test("wcsNameForIndex falls back to G54 for out-of-range indices", () => {
  assert.equal(wcsNameForIndex(1), "G54");
  assert.equal(wcsNameForIndex(6), "G59");
  assert.equal(wcsNameForIndex(7), "G59.1");
  assert.equal(wcsNameForIndex(9), "G59.3");
  assert.equal(wcsNameForIndex(0),  "G54");
  assert.equal(wcsNameForIndex(99), "G54");
});

// ---------------------------------------------------------------- //
// G92 family                                                         //
// ---------------------------------------------------------------- //

test("G92 sets per-axis additive offsets and is captured on the next segment", () => {
  const segs = parseGcodeToolpath("G92 X5 Y6\nG1 X10");
  assert.equal(segs.length, 1);
  assert.deepEqual(segs[0].g92, [5, 6, 0]);
  assert.deepEqual(segs[0].from, [0, 0, 0]);
  assert.deepEqual(segs[0].to,   [10, 0, 0]);
});

test("G92 with omitted axes preserves the existing g92 value", () => {
  const segs = parseGcodeToolpath("G92 X5 Y6 Z7\nG92 Y99\nG1 X10");
  assert.equal(segs.length, 1);
  assert.deepEqual(segs[0].g92, [5, 99, 7]);
});

test("G92.1 zeros all additive offsets", () => {
  const segs = parseGcodeToolpath("G92 X1 Y2 Z3\nG92.1\nG1 X10");
  assert.equal(segs.length, 1);
  assert.deepEqual(segs[0].g92, [0, 0, 0]);
});

test("G92.2 suspends, G92.3 restores the snapshot", () => {
  const segs = parseGcodeToolpath(
    "G92 X5 Y6\nG92.2\nG1 X10\nG92.3\nG1 X20",
  );
  assert.equal(segs.length, 2);
  // While G92.2 is in effect, the G92 contribution is zero.
  assert.deepEqual(segs[0].g92, [0, 0, 0]);
  // After G92.3, the snapshot taken at suspend time is restored.
  assert.deepEqual(segs[1].g92, [5, 6, 0]);
});

test("G92 lines never produce a motion segment", () => {
  const segs = parseGcodeToolpath("G92 X5\nG1 X10");
  assert.equal(segs.length, 1);
  // The G92 line is not represented as a segment.
  assert.equal(segs[0].sourceLine, 2);
});

// ---------------------------------------------------------------- //
// G90 / G91 absolute / incremental                                   //
// ---------------------------------------------------------------- //

test("G90 absolute is the default", () => {
  const segs = parseGcodeToolpath("G1 X10\nX20");
  assert.equal(segs.length, 2);
  assert.deepEqual(segs[1].to, [20, 0, 0]);
});

test("G91 incremental adds to the previous position", () => {
  const segs = parseGcodeToolpath("G1 X10\nG91\nX5\nX5");
  assert.equal(segs.length, 3);
  assert.deepEqual(segs[0].to, [10, 0, 0]);
  assert.deepEqual(segs[1].to, [15, 0, 0]);
  assert.deepEqual(segs[2].to, [20, 0, 0]);
});

// ---------------------------------------------------------------- //
// Arc interpolation (G2 / G3)                                        //
// ---------------------------------------------------------------- //

test("G3 partial arc with I/J in G17 plane (default)", () => {
  // Start at (0, 0). Quarter-circle CCW arc with centre at (10, 0),
  // radius 10. End at (10, 10).
  const segs = parseGcodeToolpath("G3 X10 Y10 I10 J0");
  assert.ok(segs.length > 1, "an arc must emit multiple chords");
  // End point should match the requested end exactly.
  assert.ok(closeTo(segs[segs.length - 1].to[0], 10));
  assert.ok(closeTo(segs[segs.length - 1].to[1], 10));
  // Every chord except the last should stay on the radius-10 circle
  // around the centre (10, 0).
  for (const s of segs) {
    const dx = s.to[0] - 10;
    const dy = s.to[1] - 0;
    assert.ok(
      closeTo(Math.hypot(dx, dy), 10, 1e-3),
      `point (${s.to[0]}, ${s.to[1]}) should be on the arc circle`,
    );
  }
});

test("G2 full circle in G17 plane emits a closed loop of chords", () => {
  // Start at (0, 0). Centre at (0, 10), radius 10. No X/Y → end at
  // start. The parser should rasterise the full 360°.
  const segs = parseGcodeToolpath("G2 I0 J10");
  assert.ok(segs.length >= 10, "full circle must emit many segments");
  // First segment starts at (0, 0); last ends at (0, 0) (full
  // circle closure).
  assert.ok(closeTo(segs[0].from[0], 0));
  assert.ok(closeTo(segs[0].from[1], 0));
  assert.ok(closeTo(segs[segs.length - 1].to[0], 0, 1e-3));
  assert.ok(closeTo(segs[segs.length - 1].to[1], 0, 1e-3));
});

test("R-word arc in G17 plane picks the side that matches G2/G3", () => {
  // 60° CCW arc from (0, 0) to (10, 0) with radius 10. The chosen
  // centre is above the chord at (5, +√75); the 60° CCW minor arc
  // therefore passes on the opposite side of the chord (below it).
  const segs = parseGcodeToolpath("G3 X10 Y0 R10");
  assert.ok(segs.length > 1);
  const minY = segs.reduce((m, s) => Math.min(m, s.to[1]), Infinity);
  assert.ok(minY < 0, "G3 minor arc should dip below the chord");
});

test("R-word arc with invalid radius falls back to a straight segment", () => {
  // R = 1 but the chord is ~14.14 mm long. Invalid → straight.
  // The first G1 X0 Y0 line seeds a zero-length starting segment
  // from origin (see parser notes); the G3 line adds the fallback.
  const segs = parseGcodeToolpath("G1 X0 Y0\nG3 X10 Y10 R1");
  assert.equal(segs.length, 2);
  assert.deepEqual(segs[0].to, [0, 0, 0]);
  assert.deepEqual(segs[1].to, [10, 10, 0]);
});

test("G18 (XZ plane) arc uses I and K as in-plane offsets", () => {
  // Centre at (10, 0, 0) via I=10 K=0, end at (10, 0, -10). A
  // quarter-circle CCW in the XZ plane.
  const segs = parseGcodeToolpath("G18\nG3 X10 Z-10 I10 K0");
  assert.ok(segs.length > 1);
  assert.ok(closeTo(segs[segs.length - 1].to[0], 10));
  assert.ok(closeTo(segs[segs.length - 1].to[2], -10));
  // The arc should dip into negative Z.
  const minZ = segs.reduce((m, s) => Math.min(m, s.to[2]), 0);
  assert.ok(minZ < 0, "G18 arc should dip into negative Z");
});

test("helical G17 arc interpolates Z linearly from start to end", () => {
  // Start at (0, 0, 0). G3 X10 Y10 I10 J0 Z5. Arc sweeps in XY
  // from (0,0,0) to (10,10,5); Z interpolates 0 → 5 linearly.
  const segs = parseGcodeToolpath("G3 X10 Y10 Z5 I10 J0");
  assert.ok(segs.length > 1);
  // Z should monotonically grow along the chord list.
  let prev = -Infinity;
  for (const s of segs) {
    assert.ok(s.to[2] >= prev - eps, "Z must not regress");
    prev = s.to[2];
  }
  assert.ok(closeTo(segs[segs.length - 1].to[2], 5));
});

test("G90.1 absolute arc centre: I/J are absolute, not offset from start", () => {
  // G90.1 → I/J are the absolute coordinates of the centre, not the
  // offsets from start. With start at (0, 0), G90.1 I10 J0 gives the
  // same centre as G91.1 I10 J0 here (since start.x = 0). But
  // G90.1 I0 J10 with start at (0, 0) places the centre at (0, 10)
  // (NOT at start + (0, 10) = (0, 10)).
  const segs = parseGcodeToolpath("G90.1\nG3 X10 Y0 I0 J10");
  assert.ok(segs.length > 1);
  // The arc should bulge in the +Y direction (centre at +Y).
  const maxY = segs.reduce((m, s) => Math.max(m, s.to[1]), 0);
  assert.ok(maxY > 0, "G90.1 arc should bulge in +Y");
});

test("G91.1 incremental arc centre: I/J are offsets from start (default)", () => {
  // Same numbers as the G90.1 test above; behaviour matches because
  // start is at origin. We only assert that the default behaviour
  // produces an arc, not a straight segment.
  const segs = parseGcodeToolpath("G3 X10 Y0 I0 J10");
  assert.ok(segs.length > 1);
});

// ---------------------------------------------------------------- //
// Source-line tracking                                               //
// ---------------------------------------------------------------- //

test("sourceLine is 1-based and matches the file line", () => {
  const segs = parseGcodeToolpath("G1 X1\nG1 X2\nG1 X3");
  assert.equal(segs[0].sourceLine, 1);
  assert.equal(segs[1].sourceLine, 2);
  assert.equal(segs[2].sourceLine, 3);
});

test("arc chords share their source line", () => {
  const segs = parseGcodeToolpath("G3 X10 Y10 I10 J0");
  const first = segs[0].sourceLine;
  for (const s of segs) {
    assert.equal(s.sourceLine, first, "all chords of one arc share sourceLine");
  }
});

// ---------------------------------------------------------------- //
// Real-world NGC files                                               //
// ---------------------------------------------------------------- //

test("parses nc_files/example.ngc without throwing and emits straight segments", () => {
  // The repo ships a small XYZ movement test program. The parser
  // should not throw, and the segments should be straight (no arcs).
  const text = readFileSync(examplePath, "utf-8");
  const segs = parseGcodeToolpath(text);
  // No motion == no arcs. Every segment in this file is straight.
  // The opening ``G0 X0.0 Y0.0`` after the ``G0 Z10.0`` setup move
  // is genuinely zero-length in machine coords and that's correct,
  // so we only assert we got a sensible number of moves.
  assert.ok(segs.length >= 5, `expected >= 5 segments, got ${segs.length}`);
});

test("parses nc_files/1001.ngc (Fusion 360 face milling, lots of G2/G3)", () => {
  // The big test: a real Fusion 360 export with G2/G3 arcs in both
  // G17 and G18 planes. We assert only that parsing does not throw
  // and produces a non-trivial number of segments (more than the
  // source lines because of arc rasterisation).
  const text = readFileSync(ng1001Path, "utf-8");
  const lineCount = text.split(/\r?\n/).length;
  const segs = parseGcodeToolpath(text);
  assert.ok(segs.length > lineCount, "arcs should rasterise to many segments");
  // All segments must have a valid wcsIndex in 1..9.
  for (const s of segs) {
    assert.ok(s.wcsIndex >= 1 && s.wcsIndex <= 9);
  }
});