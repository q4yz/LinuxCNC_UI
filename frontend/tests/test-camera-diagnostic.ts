// Structural guard for the camera diagnostic wiring: the store must
// expose a probe action that hits the new /stream/diagnostic endpoint
// and CameraViewer must call it (not just refreshStreamMessage) on
// stream failure so the operator sees WHY the camera is down — not
// only the supervisor-status fallback.
//
// Run with: ``node --test frontend/tests/test-camera-diagnostic.ts``

import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");
const src = resolve(repoRoot, "frontend/src");

const read = (rel) => readFileSync(resolve(src, rel), "utf-8");

test("store exposes a probe action that hits /stream/diagnostic", () => {
  const text = read("stores/cameraStore.ts");

  assert.match(
    text,
    /DIAGNOSTIC_URL.*stream\/diagnostic/,
    "store must declare the new diagnostic endpoint URL",
  );
  assert.match(
    text,
    /async function probeStreamFailure\(/,
    "store must expose a probe action",
  );
  assert.match(
    text,
    /probeStreamFailure,/,
    "store must export probeStreamFailure",
  );
});

test("CameraViewer calls probeStreamFailure on stream error", () => {
  const text = read("components/camera/CameraViewer.vue");

  // The viewer's error handler must invoke the probe so the operator
  // sees the upstream verdict (unreachable / login / 401) — not just
  // the supervisor status which is empty for IP cameras.
  assert.match(
    text,
    /probeStreamFailure\(\)/,
    "CameraViewer's handleStreamError must call probeStreamFailure",
  );
  // The probe is reachable via the store export added above.
  assert.match(
    text,
    /void store\.probeStreamFailure\(\)/,
    "CameraViewer must await the probe (void to avoid blocking retries)",
  );
});
