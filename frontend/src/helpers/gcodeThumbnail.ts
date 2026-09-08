// Slicer-style thumbnail generation for G-code uploads.
//
// Cura / PrusaSlicer / Orca embed a preview PNG at the top of the
// exported program as a base64 comment block. Files sliced without
// one (or hand-written) get the same treatment here at upload time:
// the existing toolpath parser (`parsers/gcodeParser.ts` — the same
// one the coordinate viewer uses) produces the segments, a 2D canvas
// renders them top-down (X/Y, Z up = looking from Z+ towards Z−),
// and the standard block is prepended to the text before upload.
//
// The block is written INTO the file, so the thumbnail renders
// everywhere — this app's file list, OctoPrint, any slicer-aware
// tool. Files that already carry a thumbnail are never modified.

import type { ParsedSegment } from "../parsers/gcodeParser";

const DATA_URL_PREFIX = "data:image/png;base64,";

/** True when the text already carries a `; thumbnail begin` block. */
export function hasEmbeddedThumbnail(text: string): boolean {
  return /^\s*;\s*thumbnail\s+_?begin/im.test(text);
}

/**
 * Render the toolpath top-down (X→right, Y→up) and encode it as a
 * PrusaSlicer-style thumbnail comment block. Returns `null` when
 * there are no motion segments or no canvas is available — the file
 * is then left untouched.
 */
export function buildThumbnailBlock(
  segments: ParsedSegment[],
  width = 220,
  height = 124,
): string | null {
  if (segments.length === 0) return null;
  if (typeof document === "undefined") return null;

  // Bounds (X/Y only — a top-down preview ignores Z).
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const seg of segments) {
    for (const point of [seg.from, seg.to]) {
      if (point[0] < minX) minX = point[0];
      if (point[1] < minY) minY = point[1];
      if (point[0] > maxX) maxX = point[0];
      if (point[1] > maxY) maxY = point[1];
    }
  }

  const margin = 8;
  const spanX = Math.max(maxX - minX, 1e-6);
  const spanY = Math.max(maxY - minY, 1e-6);
  const scale = Math.min(
    (width - 2 * margin) / spanX,
    (height - 2 * margin) / spanY,
  );
  // Center the drawing inside the margins. Canvas Y grows downward —
  // flip it so +Y in the part reads as up.
  const offsetX = (width - 2 * margin - spanX * scale) / 2 + margin;
  const offsetY = (height - 2 * margin - spanY * scale) / 2 + margin;
  const toCanvasX = (x: number): number => offsetX + (x - minX) * scale;
  const toCanvasY = (y: number): number => height - (offsetY + (y - minY) * scale);

  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;

  // Viewer palette: dark background, blue toolpath.
  ctx.fillStyle = "#0b0f19";
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = "#60a5fa";
  ctx.lineWidth = 1.5;
  ctx.lineCap = "round";
  ctx.beginPath();
  for (const seg of segments) {
    ctx.moveTo(toCanvasX(seg.from[0]), toCanvasY(seg.from[1]));
    ctx.lineTo(toCanvasX(seg.to[0]), toCanvasY(seg.to[1]));
  }
  ctx.stroke();

  const b64 = canvas.toDataURL("image/png").slice(DATA_URL_PREFIX.length);
  return `; thumbnail begin ${width}x${height} ${b64.length}\n${b64}\n; thumbnail end\n`;
}

/**
 * Returns the text with a thumbnail block prepended when it doesn't
 * already carry one — otherwise the text, unchanged.
 */
export function ensureEmbeddedThumbnail(
  text: string,
  segments: ParsedSegment[],
): string {
  if (hasEmbeddedThumbnail(text)) return text;
  const block = buildThumbnailBlock(segments);
  return block ? block + text : text;
}
