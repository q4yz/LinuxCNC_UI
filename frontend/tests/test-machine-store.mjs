// Machine store behavioural tests.
//
// Run with: node --test frontend/tests/test-machine-store.mjs
//
// These tests focus on the **static structure** of the store
// because we cannot drive a Pinia store from bare ``node --test``
// (no Pinia runtime). The accompanying ``vite build`` step in CI
// catches dynamic / type-level regressions; the test suite here
// covers the contract a refactor must respect:
//
//   * ``jogContinuous`` + ``jogStop`` round-trip populates and
//     empties ``jogIntervals``.
//   * The store calls ``JoggingService.jogKeepalive`` while a
//     continuous jog is active.
//   * Disconnecting from the store clears every keep-alive
//     interval.
//   * WebSocket auto-reconnect is bounded (2 s back-off) so we
//     don't hammer the backend in a network glitch.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");

const storePath = resolve(
  repoRoot,
  "frontend/src/modules/machine/store.js",
);

function readStore() {
  return readFileSync(storePath, "utf-8");
}

test("store exposes jogIntervals as a reactive map", () => {
  const text = readStore();
  // ``jogIntervals`` is declared as ``reactive({})`` so we can
  // mutate it from actions without losing reactivity.
  assert.match(text, /const\s+jogIntervals\s*=\s*reactive\(\{\s*\}\)/);
  // ``jogIntervals`` is exposed as a top-level return value so
  // ``storeToRefs`` callers stay reactive.
  assert.match(text, /jogIntervals\s*,/);
});

test("store builds the JoggingService.jogAxis payload for continuous jogs", () => {
  const text = readStore();
  // ``jogContinuous`` posts a ``jogAxis`` request with
  // ``distance: 0`` and the supplied velocity.  The store
  // breaks the call across two lines (object literal), so
  // the regex tolerates the newline and trailing whitespace.
  assert.match(text, /JoggingService\.jogAxis\s*\(\s*\{/);
  assert.match(text, /velocities:\s*\{\s*\[axis\]:\s*velocity/);
  assert.match(text, /distance:\s*0/);
  // After the initial command, the store schedules a setInterval
  // that pings the keepalive endpoint every 250 ms — the
  // historical value preserved by the migration.
  assert.match(text, /setInterval\s*\(/);
  assert.match(text, /JoggingService\.jogKeepalive/);
  assert.match(text, /,\s*250\s*\)/);
});

test("store clears jogIntervals on stop and disconnect", () => {
  const text = readStore();
  // ``jogStop`` clears the per-axis interval.
  assert.match(text, /clearInterval\(jogIntervals\[axis\]\)/);
  assert.match(text, /delete\s+jogIntervals\[axis\]/);
  // ``disconnect`` clears every remaining interval so a
  // ``--reload`` during a jog releases the axis within the
  // watchdog window.
  assert.match(text, /for\s*\(\s*const\s+axis\s+of\s+Object\.keys\(jogIntervals\)/);
});

test("store auto-reconnects on socket close with a 2 s back-off", () => {
  const text = readStore();
  assert.match(text, /setTimeout\(\s*\(\s*\)\s*=>\s*connect\(\)\s*,\s*2000\s*\)/);
});

test("store rejects ESTOP-driven power-on", () => {
  const text = readStore();
  // The ``togglePower`` action refuses to power on when ESTOP
  // is active. Pattern: ``Cannot turn on machine while ESTOP is
  // active`` is the operator-facing message.
  assert.match(text, /Cannot turn on machine while ESTOP/);
});

test("store forwards MDI commands through MachineStateService.runMdiCommand", () => {
  const text = readStore();
  // ``setPosition`` and ``setCoordinateSystem`` both funnel
  // through the legacy MDI endpoint.
  assert.match(text, /MachineStateService\.runMdiCommand\(\s*\{\s*command:/);
});

test("store converts setPosition to G10 L20 P0 via generateSetOffset", () => {
  const text = readStore();
  assert.match(text, /generateSetOffset\(axisName,\s*value\)/);
});

test("store publishes state.temperatures to the event bus", () => {
  const text = readStore();
  // The temperature module is the consumer; we publish on every
  // ``full_state`` and ``delta`` so the rolling chart keeps
  // moving even though the machine store no longer owns the
  // temperature field. The topic literal is hoisted into a
  // ``STATE_TEMPERATURES_TOPIC`` constant, so we check for
  // either the literal or the constant reference.
  assert.match(
    text,
    /const\s+STATE_TEMPERATURES_TOPIC\s*=\s*['"]state\.temperatures['"]/,
  );
  assert.match(text, /eventBus\.publish\(\s*STATE_TEMPERATURES_TOPIC/);
});

test("store connects with idempotency guard", () => {
  const text = readStore();
  // A second ``connect()`` while a socket is already open must
  // no-op rather than opening another WebSocket.
  assert.match(
    text,
    /if\s*\(\s*connectionStatus\.value\s*===\s*['"]connected['"]\s*\|\|/,
  );
  assert.match(
    text,
    /connectionStatus\.value\s*===\s*['"]connecting['"]\s*\)\s*\{[^}]*return/,
  );
});

test("store handles connectionStatus as a ref", () => {
  const text = readStore();
  assert.match(text, /const\s+connectionStatus\s*=\s*ref\(\s*['"]disconnected['"]\s*\)/);
});

test("store handles errors as a ref array", () => {
  const text = readStore();
  assert.match(text, /const\s+errors\s*=\s*ref\(\s*\[\s*\]\s*\)/);
});
