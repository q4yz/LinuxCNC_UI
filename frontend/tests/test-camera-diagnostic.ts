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

test("probe is single-flight and passes the camera id as a query param", () => {
  const text = read("stores/cameraStore.ts");

  // Single-flight guard: an <img> error burst must not stack
  // concurrent diagnostic requests (each opens the upstream once and
  // eats into the browser's 6-connection HTTP/1.1 budget).
  assert.match(
    text,
    /probeInFlight/,
    "probeStreamFailure must guard against concurrent invocations",
  );
  // ``fetch`` has no ``params`` option — the id must be encoded into
  // the URL via URLSearchParams (regression: the id was silently
  // dropped and the probe always ran against the default device).
  assert.match(
    text,
    /URLSearchParams\(\{\s*id\s*\}\)/,
    "the camera id must be encoded into the diagnostic URL query",
  );
  assert.doesNotMatch(
    text,
    /fetch\(DIAGNOSTIC_URL,\s*\{[^}]*params:/,
    "fetch must not rely on a non-existent params option",
  );
});

test("CameraViewer release→delay→open lifecycle with HTTP/1.1-safe delays", () => {
  const text = read("components/camera/CameraViewer.vue");

  // On plain HTTP the 6-connection-per-origin cap still applies, so
  // the grace period between releasing the old stream and opening
  // the new one must be long enough for the browser to reclaim the
  // slot. 300ms was too short — pinned at 1.2s.
  assert.match(
    text,
    /STREAM_CONNECT_DELAY_MS\s*=\s*1_200/,
    "stream-open grace delay must be 1.2 s",
  );
  assert.match(
    text,
    /STREAM_RETRY_BASE_MS\s*=\s*2_000/,
    "retry backoff base must be 2 s",
  );
  assert.match(
    text,
    /MAX_RETRY_DELAY_MS\s*=\s*15_000/,
    "retry backoff cap must be 15 s",
  );
  // The lifecycle must be explicit small methods, released before
  // open (regression guard for the readability refactor).
  assert.match(text, /function releaseStream\(\)/);
  assert.match(text, /function scheduleStreamOpen\(/);
  assert.match(text, /function openStream\(\)/);
  // handleStreamError must use the named backoff constants.
  assert.match(
    text,
    /STREAM_RETRY_BASE_MS \* Math\.pow\(2, retryCount - 1\)/,
    "backoff must derive from STREAM_RETRY_BASE_MS",
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
