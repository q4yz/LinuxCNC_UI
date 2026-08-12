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
//   * The store calls ``ModulesMachineService.jogKeepalive`` while a
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

test("store builds the ModulesMachineService.jogAxis payload for continuous jogs", () => {
  const text = readStore();
  // ``jogContinuous`` posts a ``jogAxis`` request with
  // ``distance: 0`` and the supplied velocity.  The store
  // breaks the call across two lines (object literal), so
  // the regex tolerates the newline and trailing whitespace.
  // (The generated client was renamed from ``JoggingService``
  // to ``ModulesMachineService`` after the legacy service
  // classes were consolidated under the module prefix.)
  assert.match(text, /ModulesMachineService\.jogAxis\s*\(\s*\{/);
  assert.match(text, /velocities:\s*\{\s*\[axis\]:\s*velocity/);
  assert.match(text, /distance:\s*0/);
  // After the initial command, the store schedules a setInterval
  // that pings the keepalive endpoint on the configured cadence —
  // the historical default is 250 ms; the runtime value lives in
  // ``keepaliveIntervalMs.value`` and is bound from the module
  // settings (with a 250 ms fallback).
  assert.match(text, /setInterval\s*\(/);
  assert.match(text, /ModulesMachineService\.jogKeepalive/);
  // The cadence is read from the module settings and falls back to
  // the historical 250 ms value.
  assert.match(text, /setInterval\([\s\S]*intervalMs\)/);
  assert.match(text, /DEFAULT_KEEPALIVE_INTERVAL_MS\s*=\s*250/);
  assert.match(text, /interval\s*<=\s*2000/);

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
  assert.match(text, /reconnectTimer\s*=\s*setTimeout\([\s\S]*connect\(\)[\s\S]*2000/);
});

test("store rejects ESTOP-driven power-on", () => {
  const text = readStore();
  // The ``togglePower`` action refuses to power on when ESTOP
  // is active. Pattern: ``Cannot turn on machine while ESTOP is
  // active`` is the operator-facing message.
  assert.match(text, /Cannot turn on machine while ESTOP/);
});

test("store forwards MDI commands through ModulesMachineService.runMdiCommand", () => {
  const text = readStore();
  // ``setPosition`` and ``setCoordinateSystem`` both funnel
  // through the legacy MDI endpoint. (The generated client was
  // renamed from ``MachineStateService`` to
  // ``ModulesMachineService`` after the legacy service classes
  // were consolidated under the module prefix.)
  assert.match(text, /ModulesMachineService\.runMdiCommand\(\s*\{\s*command:/);
});

test("store converts setPosition to G10 L20 P0 via generateSetOffset", () => {
  const text = readStore();
  assert.match(text, /generateSetOffset\(axisName,\s*value\)/);
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

test("store routes LinuxCNC WS errors through the console store with popup", () => {
  // Regression guard for the silent-bug where the WebSocket
  // ``error`` branch only logged to the browser devtools console
  // (console.error) instead of routing through ``useConsoleStore()``,
  // so the operator's ``ConsolePanel`` never saw the row and the
  // toast never fired. ``popup: true`` is required because
  // ``core/console.js`` short-circuits ``_emitToast`` when the
  // flag is missing.
  const text = readStore();
  assert.match(
    text,
    /payload\.type === "error"[\s\S]*?useConsoleStore\(\)\.error\([\s\S]*?popup:\s*true/,
    "the WS error branch must call useConsoleStore().error() with popup:true",
  );
});

test("store replays full_state errors through the console store", () => {
  // The backend keeps a bounded error history on ``SharedMachineState``
  // and ships it on ``full_state``. The frontend replays those
  // entries through ``useConsoleStore().error()`` so the operator's
  // ``ConsolePanel`` shows the backlog on reload / reconnect.
  const text = readStore();
  assert.match(
    text,
    /payload\.type === "full_state"[\s\S]*?useConsoleStore\(\)\.error\([\s\S]*?popup:\s*true/,
    "the full_state branch must replay historical errors via useConsoleStore",
  );
});
