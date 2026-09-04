// Machine store behavioural tests.
//
// Run with: node --test frontend/tests/test-machine-store.mjs
//
// The machine store lives at ``stores/machine.ts`` (the runtime
// layer). It composes ``stores/servoThread.ts`` for the 10 Hz
// WebSocket telemetry (which owns the transport) and adds the
// machine-specific actions (jog, home, set position, program
// lifecycle, settings). These tests cover the contract the store
// must respect after the servo/base split:
//
//   * ``jogContinuous`` + ``jogStop`` round-trip populates and
//     empties ``jogIntervals``.
//   * The keep-alive ping goes over the WebSocket via
//     ``servo.send({type: "jog_keepalive", ...})`` — no REST
//     round-trip per axis per 250 ms.
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
  "frontend/src/stores/machine.ts",
);
const facadePath = resolve(
  repoRoot,
  "frontend/src/facades/servoThreadFacade.ts",
);
const jogControlsPath = resolve(
  repoRoot,
  "frontend/src/components/machine/JogControls.vue",
);

function readStore() {
  return readFileSync(storePath, "utf-8");
}

function readFacade() {
  return readFileSync(facadePath, "utf-8");
}

function readJogControls() {
  return readFileSync(jogControlsPath, "utf-8");
}

test("servo-thread facade owns jogIntervals (the singleton service tracks per-axis timers)", () => {
  // After the servo/base + store/facade split the per-axis
  // keep-alive map (``jogIntervals``) lives inside the
  // ``ServoThreadService`` class on the facade, not in the
  // machine store. The machine store delegates to
  // ``servoThreadService.jogContinuous`` / ``jogStop`` so the
  // timers are cleared in one place. Pin the ownership here so a
  // future contributor does not re-introduce a parallel map in
  // ``stores/machine.ts``.
  const text = readFacade();
  assert.match(
    text,
    /private\s+jogIntervals\s*:\s*Record<number,\s*number>\s*=\s*\{\s*\}/,
    "ServoThreadService.jogIntervals must be a Record<number, number> initialised to {}",
  );
  assert.match(text, /window\.clearInterval\(this\.jogIntervals\[axis\]\)/);
  assert.match(text, /delete\s+this\.jogIntervals\[axis\]/);
  // ``clearAllJogIntervals`` is the bulk path used on WS close
  // and unmount — keep it around even after the per-axis path
  // looks complete.
  assert.match(text, /clearAllJogIntervals\s*\(\s*\)/);
});

test("servo-thread facade builds the jog-axis payload over the WebSocket for continuous jogs", () => {
  // ``jogContinuous`` posts a ``jog_axis`` event over the
  // ``/ws/telemetry`` channel with ``distance: 0`` and the
  // supplied velocity. The store breaks the call across two
  // lines (object literal), so the regex tolerates the newline
  // and trailing whitespace.
  const text = readFacade();
  assert.match(text, /type:\s*["']jog_axis["']/);
  assert.match(text, /velocities:\s*\{\s*\[axis\]:\s*jogVelocity/);
  assert.match(text, /distance:\s*0/);
  // After the initial command, the facade schedules a
  // ``setInterval`` that pings the keep-alive over the open
  // WebSocket at the configured cadence — the historical default
  // is 250 ms; the runtime value is supplied by the caller.
  assert.match(text, /window\.setInterval\s*\(/);
  // Canonical: keep-alive goes over the WebSocket (no HTTP spam).
  assert.match(
    text,
    /type:\s*["']jog_keepalive["']/,
    "jogContinuous must send jog_keepalive over the WS, not REST",
  );
});

test("machine store delegates jog axis / stop to the servo-thread facade", () => {
  // The /ws/telemetry channel is bidirectional; the module store
  // routes both jog start and jog stop through the facade
  // (``servoThreadService.jogContinuous`` / ``jogStop``) so the
  // legacy REST endpoints are no longer the primary path. A
  // regression that re-introduced a direct ``servo.send`` call
  // here would bypass the per-axis keep-alive timer and leave a
  // jog running with no watchdog refresh — caught by this test.
  const text = readStore();
  assert.match(
    text,
    /servoThreadService\.jogContinuous\s*\(/,
    "jogContinuous must delegate to the facade (not send jog_axis directly)",
  );
  assert.match(
    text,
    /servoThreadService\.jogStop\s*\(/,
    "jogStop must delegate to the facade (not send jog_stop directly)",
  );
  // And the discrete ``jog`` still sends ``jog_axis`` over the
  // socket (it's a one-shot and does not need the timer path).
  assert.match(
    text,
    /servoThreadService\.send\(\s*\{\s*type:\s*["']jog_axis["']/,
    "jog (discrete) must send jog_axis over the WS",
  );
});

test("machine store does not await refreshSettings inside jogContinuous (regression)", () => {
  // Fix A — the headline "first jog does not stop on its own"
  // bug. ``refreshSettings`` is an HTTP round-trip; awaiting it
  // inside ``jogContinuous`` let a click-and-release land before
  // the WebSocket message was sent, so ``stopJog`` fired first
  // (no-op on the backend because the axis was never
  // registered) and then the late ``jog_axis`` started a jog
  // with a fresh keep-alive interval that nothing would ever
  // clear. Pin the absence of the await.
  const text = readStore();
  assert.doesNotMatch(
    text,
    /jogContinuous[\s\S]{0,400}await\s+refreshSettings\s*\(\s*\)/,
    "jogContinuous must not await refreshSettings — that await races with stopJog",
  );
  // Same fix for the discrete jog — keep it consistent so a
  // future regression that re-introduces the await in either
  // path is caught here.
  assert.doesNotMatch(
    text,
    /function\s+jog\s*\(\s*axis[\s\S]{0,400}await\s+refreshSettings\s*\(\s*\)/,
    "jog must not await refreshSettings either",
  );
});

test("machine store eagerly loads settings on instantiation (regression)", () => {
  // Fix A — companion to the await-removal test above. The
  // settings must be loaded eagerly (fire-and-forget) so the
  // first jog click lands AFTER the values have populated. The
  // promise is also cached so concurrent callers do not fire
  // duplicate HTTP round-trips.
  const text = readStore();
  assert.match(
    text,
    /void\s+refreshSettings\s*\(\s*\)/,
    "store factory must eagerly call refreshSettings() at least once",
  );
  // Idempotency: the second caller should reuse the cached
  // promise rather than re-issue the HTTP GET.
  assert.match(
    text,
    /settingsLoadPromise/,
    "refreshSettings must cache its in-flight promise to dedupe concurrent callers",
  );
});

test("JogControls handleKeyUp stops the jog even when isActive is false (regression)", () => {
  // Fix B — ``handleKeyUp`` used to early-return on
  // ``!isActive.value`` which silently dropped the stop dispatch
  // if the panel lost focus mid-hold (window blur, focusout to
  // a sibling element). The component now tracks the keys whose
  // keydown started a jog (``keysHeldForJog``) and ``handleKeyUp``
  // dispatches ``stopJog`` whenever one of those keys is
  // released — independent of focus state. Pin the ledger plus
  // the absence of the old early-return.
  const text = readJogControls();
  assert.match(
    text,
    /keysHeldForJog\s*=\s*ref\(\s*new\s+Set<string>\(\s*\)\s*\)/,
    "JogControls must declare keysHeldForJog as a Set<string>",
  );
  // The buggy early-return must be gone from handleKeyUp. Pin
  // the positive contract instead: the handler now keys on the
  // ledger, not on isActive.
  const handleKeyUpBlock = text.match(/const\s+handleKeyUp\s*=\s*\([^)]*\)\s*=>\s*\{[\s\S]*?\n\}/);
  assert.ok(handleKeyUpBlock, "handleKeyUp handler must exist");
  assert.match(
    handleKeyUpBlock[0],
    /keysHeldForJog\.value\.has\(\s*event\.code\s*\)/,
    "handleKeyUp must consult keysHeldForJog (not isActive)",
  );
  assert.doesNotMatch(
    handleKeyUpBlock[0],
    /if\s*\(\s*!\s*isActive\.value\s*\)\s*return/,
    "handleKeyUp must NOT early-return on !isActive — that was the bug",
  );
});

test("JogControls handleKeyDown records the key before dispatching the jog (regression)", () => {
  // Fix B — companion to the handleKeyUp test. ``keysHeldForJog``
  // must be populated BEFORE ``startJog`` runs so a synchronous
  // focusout between keydown and keyup cannot strand the
  // matching keyup handler. Pin the ordering: the ``add`` line
  // appears in the keydown handler before the ``startJog``
  // dispatch.
  const text = readJogControls();
  const handleKeyDownBlock = text.match(/const\s+handleKeyDown\s*=\s*\([^)]*\)\s*=>\s*\{[\s\S]*?\n\}/);
  assert.ok(handleKeyDownBlock, "handleKeyDown handler must exist");
  const addIdx = handleKeyDownBlock[0].indexOf("keysHeldForJog.value.add");
  const startIdx = handleKeyDownBlock[0].indexOf("startJog(");
  assert.ok(addIdx >= 0, "handleKeyDown must add the key to keysHeldForJog");
  assert.ok(startIdx >= 0, "handleKeyDown must dispatch startJog");
  assert.ok(
    addIdx < startIdx,
    "handleKeyDown must record the key in keysHeldForJog BEFORE dispatching startJog",
  );
});

test("store rejects ESTOP-driven power-on", () => {
  const text = readStore();
  // The ``togglePower`` action refuses to power on when ESTOP is
  // active. Pattern: ``Cannot turn on machine while ESTOP is
  // active`` is the operator-facing message.
  assert.match(text, /Cannot turn on machine while ESTOP/);
});

test("store forwards MDI commands through ModulesMachineStateService.runMdiCommand", () => {
  // MDI dispatch (setPosition / setCoordinateSystem) is handled by
  // ``machineStateFacade.ts``, which the store delegates to — not
  // the store itself. After the state-module extraction, MDI lives
  // in ``backend.system... machine_state`` router (tag
  // ``modules:machine_state``); the regenerated client wrapper is
  // ``ModulesMachineStateService``. ``homeAxis`` stays on
  // ``ModulesAxisService`` because homing is an axis action.
  const text = readFileSync(
    resolve(repoRoot, "frontend/src/facades/machineStateFacade.ts"),
    "utf-8",
  );
  assert.match(text, /ModulesMachineStateService\.runMdiCommand\(\s*\{\s*command:/);
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

test("store does NOT call the removed compat shim", () => {
  // The compat shim (formerly ``stores/machineStoreShim.js``) is
  // gone — the machine module is now a hard dependency. A
  // regression that re-introduces a registration call would
  // re-bloat the cross-module surface.
  const text = readStore();
  assert.doesNotMatch(
    text,
    /registerMachineStore\s*\(/,
    "stores/machine.js must not call the removed registerMachineStore",
  );
  assert.doesNotMatch(
    text,
    /unregisterMachineStore\s*\(/,
    "stores/machine.js must not call the removed unregisterMachineStore",
  );
  assert.doesNotMatch(
    text,
    /import\s*\{[^}]*registerMachineStore[^}]*\}/,
  );
});

test("store exposes updateAxisSettings action routed through the axis facade", () => {
  const text = readStore();
  assert.match(
    text,
    /import\s*\{[^}]*axisFacade[^}]*\}\s*from\s*["']\.\.\/facades\/axisFacade/,
    "stores/machine.ts must import the axis facade",
  );
  assert.match(
    text,
    /async\s+function\s+updateAxisSettings\s*\(/,
    "stores/machine.ts must define updateAxisSettings",
  );
  assert.match(
    text,
    /axisFacade\.updateSettings\s*\(/,
    "updateAxisSettings must delegate to axisFacade.updateSettings",
  );
  assert.match(
    text,
    /updateAxisSettings\b/,
    "updateAxisSettings must be referenced inside the store's return object",
  );
});

test("axis facade wraps ModulesAxisService.axisSettings", () => {
  const facadeText = readFileSync(
    resolve(repoRoot, "frontend/src/facades/axisFacade.ts"),
    "utf-8",
  );
  assert.match(
    facadeText,
    /async\s+function\s+updateSettings\s*\(\s*multiplier\s*:[\s\S]*?absoluteSpeedLimit\s*:/,
    "axisFacade must define updateSettings",
  );
  assert.match(
    facadeText,
    /ModulesAxisService\.axisSettings\(\s*\{\s*multiplier,\s*absolute_speed_limit:\s*absoluteSpeedLimit\s*,?\s*\}\s*\)/,
    "axisFacade.updateSettings must call ModulesAxisService.axisSettings with both fields",
  );
  assert.match(
    facadeText,
    /updateSettings\b/,
    "axisFacade must export updateSettings",
  );
});