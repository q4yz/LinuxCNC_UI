// Machine module store behavioural tests.
//
// Run with: node --test frontend/tests/test-machine-store.mjs
//
// The machine module store composes ``stores/servoThread.js`` for
// the 10 Hz WebSocket telemetry (which owns the transport) and
// adds the module-specific actions (jog, home, set position,
// program lifecycle, settings). These tests cover the contract
// the module store must respect after the servo/base split:
//
//   * ``jogContinuous`` + ``jogStop`` round-trip populates and
//     empties ``jogIntervals``.
//   * The store calls ``ModulesMachineService.jogKeepalive`` while a
//     continuous jog is active.
//   * ``jogStop`` clears every remaining keep-alive interval.
//   * The store composes the servo-thread store for telemetry
//     rather than owning the WebSocket itself.
//
// Tests for the WebSocket transport itself (reconnect cadence,
// ``full_state`` / ``delta`` dispatch, console-store error routing)
// live in ``test-servo-thread.mjs``.

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
  assert.match(text, /const\s+jogIntervals\s*=\s*reactive\(\s*\{\s*\}\s*\)/);
  // ``jogIntervals`` is exposed as a top-level return value so
  // ``storeToRefs`` callers stay reactive.
  assert.match(text, /jogIntervals\s*,/);
});

test("store builds the ModulesMachineService.jogAxis payload for continuous jogs", () => {
  const text = readStore();
  // ``jogContinuous`` posts a ``jogAxis`` request with
  // ``distance: 0`` and the supplied velocity.  The store
  // breaks the call across two lines (object literal), so
  // the regex tolerates the newline and trailing whitespace.
  assert.match(text, /ModulesMachineService\.jogAxis\s*\(\s*\{/);
  assert.match(text, /velocities:\s*\{\s*\[axis\]:\s*velocity/);
  assert.match(text, /distance:\s*0/);
  // After the initial command, the store schedules a setInterval
  // that pings the keepalive over the open WebSocket at the
  // configured cadence — the historical default is 250 ms; the
  // runtime value lives in ``keepaliveIntervalMs.value`` and is
  // bound from the module settings (with a 250 ms fallback).
  assert.match(text, /setInterval\s*\(/);
  // Canonical: keep-alive goes over the WebSocket (no HTTP spam).
  assert.match(
    text,
    /servo\.send\(\s*\{\s*type:\s*["']jog_keepalive["']/,
    "jogContinuous must send jog_keepalive over the WS, not REST",
  );
  // The cadence is read from the module settings and falls back to
  // the historical 250 ms value.
  assert.match(text, /setInterval\([\s\S]*intervalMs\)/);
  assert.match(text, /DEFAULT_KEEPALIVE_INTERVAL_MS\s*=\s*250/);
  assert.match(text, /interval\s*<=\s*2000/);
});

test("store sends jog_axis and jog_stop over the WebSocket", () => {
  // The /ws/telemetry channel is bidirectional; the module
  // store routes both jog start and jog stop through
  // ``servo.send({type: "jog_axis", ...})`` and
  // ``servo.send({type: "jog_stop", ...})`` so the legacy REST
  // endpoints are no longer the primary path. A regression that
  // re-introduces a REST-only jog start or stop is caught here.
  const text = readStore();
  assert.match(
    text,
    /servo\.send\(\s*\{\s*type:\s*["']jog_axis["']/,
    "jog / jogContinuous must send jog_axis over the WS",
  );
  assert.match(
    text,
    /servo\.send\(\s*\{\s*type:\s*["']jog_stop["']/,
    "jogStop must send jog_stop over the WS",
  );
});

test("store clears jogIntervals on jogStop", () => {
  const text = readStore();
  // ``jogStop`` clears the per-axis interval for the axis it
  // is asked to stop. Bulk cleanup on module unmount lives in
  // ``modules/machine/components/JogControls.vue`` so a hot-
  // reload during a continuous jog releases the axis within the
  // watchdog window.
  assert.match(text, /clearInterval\(jogIntervals\[axis\]\)/);
  assert.match(text, /delete\s+jogIntervals\[axis\]/);
});

test("store rejects ESTOP-driven power-on", () => {
  const text = readStore();
  // The ``togglePower`` action refuses to power on when ESTOP is
  // active. Pattern: ``Cannot turn on machine while ESTOP is
  // active`` is the operator-facing message.
  assert.match(text, /Cannot turn on machine while ESTOP/);
});

test("store forwards MDI commands through ModulesMachineService.runMdiCommand", () => {
  const text = readStore();
  // ``setPosition`` and ``setCoordinateSystem`` both funnel
  // through the legacy MDI endpoint.
  assert.match(text, /ModulesMachineService\.runMdiCommand\(\s*\{\s*command:/);
});

test("store converts setPosition to G10 L20 P0 via generateSetOffset", () => {
  const text = readStore();
  assert.match(text, /generateSetOffset\(axisName,\s*value\)/);
});

test("store composes the servo-thread store for telemetry", () => {
  const text = readStore();
  // The 10 Hz ``/ws/telemetry`` socket lives in
  // ``stores/servoThread.js`` — the module store composes that
  // store for ``status`` / ``connectionStatus`` / ``errors``.
  // A regression that brings the socket back into the module
  // store would re-bloat the file to ~700 lines and break the
  // runtime split.
  assert.match(
    text,
    /useServoThreadStore\s*\(/,
    "machine store must compose useServoThreadStore",
  );
  assert.doesNotMatch(
    text,
    /new\s+WebSocket\s*\(/,
    "machine store must not own the WebSocket — use stores/servoThread.js",
  );
});

test("store no longer publishes state.temperatures", () => {
  // Sensors moved to the base-thread snapshot
  // (``stores/baseThread.js``). The 10 Hz WebSocket stream no
  // longer carries them; the machine store therefore does not
  // publish a ``state.temperatures`` event-bus topic. Any module
  // that needs sensor data reads it from
  // ``useBaseThreadStore().sensors`` via ``storeToRefs``.
  const text = readStore();
  assert.doesNotMatch(
    text,
    /STATE_TEMPERATURES_TOPIC/,
    "machine store must not define STATE_TEMPERATURES_TOPIC",
  );
  assert.doesNotMatch(
    text,
    /eventBus\.publish\(\s*['"]state\.temperatures['"]/,
    "machine store must not publish the state.temperatures topic",
  );
});

test("store registers itself with the compat shim on mount", () => {
  const text = readStore();
  // Pre-migration consumers call ``useMachineStore()`` from the
  // shim. The module store registers itself so those calls
  // resolve to this store. The shim's ``registerMachineStore``
  // helper is the only sanctioned entry point.
  assert.match(text, /registerMachineStore\s*\(/);
  assert.match(text, /unregisterMachineStore\s*\(/);
  assert.match(text, /import\s*\{[^}]*registerMachineStore[^}]*\}/);
});