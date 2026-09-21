// Web Worker: builds the toolpath's position/color Float32Arrays and
// bounding box off the main thread.
//
// `ToolpathViewer.vue` used to do this synchronously on every
// `segments` prop change — for a large real-world G-code file
// (tens of thousands of segments) that's a genuine multi-second
// main-thread stall, the same class of freeze this app's NGC viewer
// already had to be fixed for elsewhere (fill-rate / main-thread
// saturation). The fix here is the same idea applied to file
// previews: move the allocation + bounds loop into a worker, then
// hand the finished `Float32Array`s back as transferable objects
// (`postMessage(..., [positions.buffer, colors.buffer])`) — a
// zero-copy handoff, not a structured-clone of the whole buffer.
//
// Deliberately dependency-free (no THREE.js import here) — bounds
// come back as a plain `{minX, minY, minZ, maxX, maxY, maxZ}` object,
// not a `THREE.Box3`, so the worker bundle stays lean and doesn't
// need a WebGL-capable global scope at all.
/// <reference lib="webworker" />

import type { ParsedSegment } from "../parsers/gcodeParser";

// Same palette `ToolpathViewer.vue` already used (pending = blue) —
// this preview never distinguishes already-cut segments (no live
// telemetry / motionLine involved, it's a static file preview), so
// every segment gets the one color.
const COLOR_PENDING_R = 0x60 / 255;
const COLOR_PENDING_G = 0xa5 / 255;
const COLOR_PENDING_B = 0xfa / 255;

export interface ToolpathWorkerRequest {
  jobId: number;
  segments: ParsedSegment[];
}

export interface ToolpathWorkerBounds {
  minX: number;
  minY: number;
  minZ: number;
  maxX: number;
  maxY: number;
  maxZ: number;
}

export interface ToolpathWorkerResponse {
  jobId: number;
  positions: Float32Array | null;
  colors: Float32Array | null;
  bounds: ToolpathWorkerBounds | null;
}

self.onmessage = (e: MessageEvent<ToolpathWorkerRequest>) => {
  const { jobId, segments } = e.data;
  const count = segments.length;

  if (count === 0) {
    const empty: ToolpathWorkerResponse = { jobId, positions: null, colors: null, bounds: null };
    self.postMessage(empty);
    return;
  }

  const positions = new Float32Array(count * 6);
  const colors = new Float32Array(count * 6);

  let minX = Infinity, minY = Infinity, minZ = Infinity;
  let maxX = -Infinity, maxY = -Infinity, maxZ = -Infinity;

  for (let i = 0; i < count; i++) {
    const seg = segments[i];
    const f0 = seg.from[0], f1 = seg.from[1], f2 = seg.from[2];
    const t0 = seg.to[0], t1 = seg.to[1], t2 = seg.to[2];

    // Bounds computed here too — the same loop that already visits
    // every segment to fill the position array, so this is free.
    if (f0 < minX) minX = f0; if (f0 > maxX) maxX = f0;
    if (f1 < minY) minY = f1; if (f1 > maxY) maxY = f1;
    if (f2 < minZ) minZ = f2; if (f2 > maxZ) maxZ = f2;

    if (t0 < minX) minX = t0; if (t0 > maxX) maxX = t0;
    if (t1 < minY) minY = t1; if (t1 > maxY) maxY = t1;
    if (t2 < minZ) minZ = t2; if (t2 > maxZ) maxZ = t2;

    const o = i * 6;
    positions[o] = f0;
    positions[o + 1] = f1;
    positions[o + 2] = f2;
    positions[o + 3] = t0;
    positions[o + 4] = t1;
    positions[o + 5] = t2;

    colors[o] = COLOR_PENDING_R;
    colors[o + 1] = COLOR_PENDING_G;
    colors[o + 2] = COLOR_PENDING_B;
    colors[o + 3] = COLOR_PENDING_R;
    colors[o + 4] = COLOR_PENDING_G;
    colors[o + 5] = COLOR_PENDING_B;
  }

  const bounds: ToolpathWorkerBounds = { minX, minY, minZ, maxX, maxY, maxZ };
  const response: ToolpathWorkerResponse = { jobId, positions, colors, bounds };

  // Transfer the underlying ArrayBuffers to the main thread
  // (zero-copy) instead of letting postMessage structured-clone them.
  self.postMessage(response, [positions.buffer, colors.buffer]);
};
