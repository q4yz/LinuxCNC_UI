// Behavioural tests for ``frontend/src/helpers/gcodeThumbnail.ts``.
//
// The real bug this locks down: the base64 thumbnail payload used to
// be written as ONE giant unprefixed line — no leading `;`, no width
// cap. That's exactly the "wall of text as one line" shape LinuxCNC's
// own interpreter chokes on when it actually runs the file (a
// separate concern from this app's own toolpath preview, which never
// touches the saved file). ``chunkBase64`` is the fix: every payload
// line is `;`-prefixed and capped at ``THUMBNAIL_CHUNK_WIDTH``,
// matching PrusaSlicer's own convention.
//
// ``buildThumbnailBlock`` itself needs a DOM canvas
// (``document.createElement("canvas")``), unavailable in this plain
// ``node:test`` environment (same constraint ``gcodeParser.ts``'s own
// test file notes) — so ``chunkBase64`` is tested directly, and the
// integration half (does ``parseGcodeToolpath`` correctly ignore the
// resulting block?) is verified by hand-assembling a block with it.

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  chunkBase64,
  THUMBNAIL_CHUNK_WIDTH,
  hasEmbeddedThumbnail,
} from "../src/helpers/gcodeThumbnail";
import { parseGcodeToolpath } from "../src/parsers/gcodeParser";

test("every chunked line stays within the width cap", () => {
  const b64 = "A".repeat(500);
  const chunked = chunkBase64(b64, THUMBNAIL_CHUNK_WIDTH);
  for (const line of chunked.split("\n")) {
    assert.ok(
      line.length <= THUMBNAIL_CHUNK_WIDTH + 2, // "; " prefix
      `line exceeds the width cap: ${line.length} chars`,
    );
  }
});

test("every chunked line is a semicolon comment, never a bare payload line", () => {
  const b64 = "SGVsbG8gd29ybGQ".repeat(20);
  const chunked = chunkBase64(b64, THUMBNAIL_CHUNK_WIDTH);
  for (const line of chunked.split("\n")) {
    assert.match(line, /^;\s/);
  }
});

test("chunking is lossless — rejoining every chunk reconstructs the original base64", () => {
  const b64 = "iVBORw0KGgoAAAANSUhEUgAAANwAAAB8CAYAAAACRt5v".repeat(10);
  const chunked = chunkBase64(b64, THUMBNAIL_CHUNK_WIDTH);
  const rejoined = chunked
    .split("\n")
    .map((line) => line.replace(/^;\s?/, ""))
    .join("");
  assert.equal(rejoined, b64);
});

test("no chunking needed for a payload shorter than the width cap", () => {
  const b64 = "shortpayload";
  const chunked = chunkBase64(b64, THUMBNAIL_CHUNK_WIDTH);
  assert.equal(chunked, `; ${b64}`);
});

test("hasEmbeddedThumbnail recognises a chunked, semicolon-prefixed block", () => {
  const block = [
    "; thumbnail begin 220x124 2632",
    "; iBORw0KGgoAAAANSUhEUgAAANwAAAB8CAYAAAACRt5vAAAH",
    "; aUlEQVR4AeydP27cRhSHCbcpUslAqlRKYV9A7tyrDnSHVNJ",
    "; thumbnail end",
    "",
  ].join("\n");
  assert.ok(hasEmbeddedThumbnail(block));
});

test("a chunked thumbnail block is entirely inert to the toolpath parser", () => {
  // Hand-assembled the way buildThumbnailBlock would produce it, once
  // chunked — this is the "parser understands it" contract: prepending
  // this block to real G-code must not change the parsed toolpath at
  // all, every chunk line reads as a plain full-line comment.
  const b64 = "iVBORw0KGgoAAAANSUhEUgAAANwAAAB8CAYAAAACRt5v".repeat(8);
  const block = `; thumbnail begin 220x124 ${b64.length}\n${chunkBase64(b64, THUMBNAIL_CHUNK_WIDTH)}\n; thumbnail end\n`;

  const gcode = "G1 X10 Y5\nG1 X20 Y15\n";
  const withoutThumbnail = parseGcodeToolpath(gcode);
  const withThumbnail = parseGcodeToolpath(block + gcode);

  assert.equal(withThumbnail.length, withoutThumbnail.length);
  assert.deepEqual(
    withThumbnail.map((s) => s.to),
    withoutThumbnail.map((s) => s.to),
  );
});
