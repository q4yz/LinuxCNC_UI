// Servo-thread store + facade behavioural tests.
//
// Run with: node --test frontend/tests/test-servo-thread.ts
//
// The 10 Hz ``/ws/telemetry`` WebSocket transport lives on
// ``ServoThreadService`` (``facades/servoThreadFacade.ts``), not on
// the Pinia store — ``stores/servoThread.ts`` is a thin reactive
// state container (``status``, ``connectionStatus``,
// ``lastMessageAt``) with mutation actions
// (``setFullState``/``applyDelta``/``setConnectionStatus``) that the
// facade calls into. This suite pins that split:
//
//   * The facade opens the socket in ``connect()`` and re-connects
//     with a 2 s back-off on close (unless the close was deliberate).
//   * ``full_state`` / ``delta`` / ``error`` envelope types dispatch
//     to the right handlers and mirror into the State Facade via the
//     store's own ``mirrorToFacade()``.
//   * The facade's ``error`` branch routes through
//     ``useConsoleStore().error(...)`` with ``popup: true`` — the
//     silent-bug regression guard.
//   * Historical errors on ``full_state``/``delta`` replay through
//     the console store so a reconnecting operator sees the backlog.
//   * ``stores/machine.ts`` must NOT contain ``new WebSocket(`` after
//     the servo/base split — the facade owns the only socket.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");

const servoPath = resolve(
  repoRoot,
  "frontend/src/stores/servoThread.ts",
);
const facadePath = resolve(
  repoRoot,
  "frontend/src/facades/servoThreadFacade.ts",
);
const modulePath = resolve(
  repoRoot,
  "frontend/src/stores/machine.ts",
);

function readServo() {
  return readFileSync(servoPath, "utf-8");
}

function readFacade() {
  return readFileSync(facadePath, "utf-8");
}

function readModule() {
  return readFileSync(modulePath, "utf-8");
}

test("servo-thread store file lives at stores/servoThread.js", () => {
  // The whole suite is moot if the file is missing.
  assert.ok(
    readFileSync(servoPath, "utf-8").length > 0,
    "expected frontend/src/stores/servoThread.ts to exist",
  );
});

test("servo-thread store exposes connectionStatus as a ref", () => {
  // ``errors``/``isUpdating`` are not separate store-level refs in
  // the current design — ``connectionStatus`` (four-state:
  // disconnected/connecting/connected/error-ish via console routing)
  // is the store's own transport-status signal; per-frame error
  // history lives on the ``ServoThreadState`` instance in ``status``.
  const text = readServo();
  assert.match(text, /const\s+connectionStatus\s*=\s*ref\(\s*['"]disconnected['"]\s*\)/);
});

test("servo-thread facade opens /ws/telemetry and re-connects with a 2 s back-off", () => {
  const text = readFacade();
  // The facade owns the ``new WebSocket(...)`` call.
  assert.match(text, /\/ws\/telemetry/);
  assert.match(text, /new\s+WebSocket\s*\(/);
  // 2 s reconnect back-off in ``scheduleReconnect()``.
  assert.match(
    text,
    /scheduleReconnect\s*\(\s*\)\s*\{[\s\S]*?setTimeout\s*\([\s\S]*?,\s*2000\s*\)/,
    "scheduleReconnect() must re-invoke connect() after a 2000ms setTimeout",
  );
});

test("servo-thread facade does not auto-reconnect after a deliberate disconnect", () => {
  // ``disconnect()`` flips ``manualClose`` before closing the
  // socket; ``onclose`` checks the flag before scheduling a
  // reconnect, so a deliberate close (machine went offline) does
  // not fight the app shell's own reconnect-on-heartbeat logic.
  const text = readFacade();
  assert.match(text, /disconnect\s*\(\s*\)\s*\{[\s\S]*?manualClose\s*=\s*true/);
  assert.match(text, /if\s*\(\s*this\.manualClose\s*\)\s*return/);
});

test("servo-thread routes full_state/delta envelopes to the store and mirrors to the State Facade", () => {
  // The facade dispatches on the parsed envelope type; the store's
  // own ``setFullState``/``applyDelta`` (tested separately below)
  // call ``mirrorToFacade()`` so widgets reading ``stores/stateFacade``
  // stay current for both frame types.
  const text = readFacade();
  assert.match(text, /case\s*['"]full_state['"][\s\S]*?store\.setFullState\(/);
  assert.match(text, /case\s*['"]delta['"][\s\S]*?store\.applyDelta\(/);
});

test("servo-thread facade routes LinuxCNC WS errors through the console store with popup", () => {
  // Regression guard for the silent-bug where the WebSocket
  // ``error`` branch only logged to the browser devtools console
  // (console.error) instead of routing through ``useConsoleStore()``,
  // so the operator's ``ConsolePanel`` never saw the row and the
  // toast never fired. ``popup: true`` is required so the toast
  // layer fires.
  const text = readFacade();
  assert.match(
    text,
    /case\s*['"]error['"][\s\S]*?emitLinuxCNCError\(/,
    "the WS 'error' envelope branch must route through emitLinuxCNCError",
  );
  assert.match(
    text,
    /function\s+emitLinuxCNCError[\s\S]*?consoleStore\.error\([\s\S]*?popup:\s*true/,
    "emitLinuxCNCError must call consoleStore.error() with popup:true",
  );
});

test("servo-thread facade replays full_state/delta error history through the console store", () => {
  // The backend keeps a bounded error history and ships it on
  // ``full_state`` (and any subsequent ``delta`` that changes it).
  // The frontend replays those entries through
  // ``useConsoleStore().error()`` so the operator's ``ConsolePanel``
  // shows the backlog on reload / reconnect, deduped via
  // ``replayedErrorKeys`` so a reconnect doesn't spam duplicates.
  const text = readFacade();
  assert.match(text, /case\s*['"]full_state['"][\s\S]*?this\.replayErrorHistory\(/);
  assert.match(text, /case\s*['"]delta['"][\s\S]*?this\.replayErrorHistory\(/);
  assert.match(
    text,
    /replayErrorHistory[\s\S]*?consoleStore\.error\([\s\S]*?popup:\s*true/,
    "replayErrorHistory must call consoleStore.error() with popup:true",
  );
});

test("servo-thread facade exposes a send() method for inbound WS commands", () => {
  // The /ws/telemetry channel is bidirectional. The machine store's
  // ``jogContinuous`` calls ``servoThreadService.send({type:
  // "jog_keepalive", ...})`` every 250 ms instead of POSTing to a
  // REST keepalive endpoint — the difference between 4 RTT/s/axis
  // and zero.
  const text = readFacade();
  assert.match(text, /send\s*\(\s*payload\s*:\s*object\s*\)/);
  // No-op guard when the socket isn't open.
  assert.match(text, /this\.ws\.readyState\s*===\s*WebSocket\.OPEN/);
});

test("servo-thread store exposes applyDelta that routes through status.value.patch", () => {
  // Regression guard for the silent-bug where the facade called
  // ``store.status.patch(envelope.data)`` directly. Pinia returns
  // a ``Ref<ClassInstance>`` from setup stores and the property
  // writes only flow through Vue's reactive ``Proxy`` when the
  // store's own action is the caller. The fix pins this contract:
  // ``applyDelta`` MUST delegate to ``status.value.patch(...)``
  // (not ``Object.assign`` or ``store.status.patch``).
  const text = readServo();
  assert.match(
    text,
    /const\s+applyDelta\s*=\s*\(\s*delta\s*:\s*ServoThreadStateResponse\s*\)\s*:\s*void\s*=>/,
    "applyDelta must be typed (ServoThreadStateResponse) => void",
  );
  assert.match(
    text,
    /applyDelta[\s\S]*?status\.value\.patch\(\s*delta\s*\)/,
    "applyDelta must call status.value.patch(delta) so reactivity fires",
  );
  assert.doesNotMatch(
    text,
    /applyDelta[\s\S]*?Object\.assign/,
    "applyDelta must NOT use Object.assign — bypasses the entity patch",
  );
});

test("facade routes delta frames through store.applyDelta (not store.status.patch)", () => {
  // The original breakage: ``case 'delta': store.status.patch(data)``.
  // That call returned the wrong reactive surface and the UI never
  // re-rendered. Pin the fix so a regression is caught at CI.
  const text = readFacade();
  assert.match(
    text,
    /case\s*['"]delta['"][\s\S]*?store\.applyDelta\(\s*envelope\.data\s*\)/,
    "the 'delta' branch must call store.applyDelta(envelope.data)",
  );
  assert.doesNotMatch(
    text,
    /store\.status\.patch\s*\(\s*envelope\.data\s*\)/,
    "the facade must NOT call store.status.patch directly",
  );
});

test("servo-thread store mirrors state into the State Facade on every frame", () => {
  // The State Facade (``stores/stateFacade.ts``) is the consumer
  // surface for widgets that read the high-resolution state
  // vocabulary (``systemState``, ``printProgress``,
  // ``isEstopActive``). After the TS migration the bridge was
  // severed — the facade was frozen on ``DEFAULT_RAW_STATUS`` and
  // ``EStopHeader``'s state badge was stuck on ``ESTOP``.
  // ``setFullState`` and ``applyDelta`` must each mirror the
  // new state to the facade so widgets that read from
  // ``stateFacade`` stay current.
  const text = readServo();
  assert.match(
    text,
    /const\s+mirrorToFacade\s*=\s*\(\s*\)\s*:\s*void\s*=>/,
    "the store must define mirrorToFacade()",
  );
  assert.match(
    text,
    /import\s*\{[^}]*useMachineStore[^}]*\}\s*from\s*["']\.\/stateFacade["']/,
    "the store must import the facade's useMachineStore",
  );
  assert.match(
    text,
    /useFacadeStore\s*\(\s*\)/,
    "the store must call useFacadeStore() inside mirrorToFacade",
  );
  // Both ingress paths must mirror.
  const setFullBlock = text.match(
    /setFullState[\s\S]*?return\s*\{[\s\S]*?\}\s*\)\s*;?/,
  );
  assert.ok(setFullBlock, "setFullState must exist");
  assert.match(
    setFullBlock[0],
    /mirrorToFacade\s*\(\s*\)/,
    "setFullState must call mirrorToFacade()",
  );
  const applyDeltaBlock = text.match(
    /applyDelta[\s\S]*?return\s*\{[\s\S]*?\}\s*\)\s*;?/,
  );
  assert.ok(applyDeltaBlock, "applyDelta must exist");
  assert.match(
    applyDeltaBlock[0],
    /mirrorToFacade\s*\(\s*\)/,
    "applyDelta must call mirrorToFacade()",
  );
});

test("DebugPanel reads telemetry from useServoThreadStore, not useMachineStore", () => {
  // ``stores/machine.ts`` only exposes ``defaultJogVelocity`` /
  // ``keepaliveIntervalMs`` as state after the migration —
  // ``status`` is a computed. Reading ``store.$state`` here was
  // the reason the panel showed only those two fields.
  const debugPath = resolve(
    repoRoot,
    "frontend/src/components/DebugPanel.vue",
  );
  const text = readFileSync(debugPath, "utf-8");
  assert.match(
    text,
    /from\s*["']\.\.\/stores\/servoThread["']/,
    "DebugPanel must import from stores/servoThread",
  );
  assert.doesNotMatch(
    text,
    /from\s*["']\.\.\/stores\/machine["']/,
    "DebugPanel must NOT import from stores/machine (status moved out of $state)",
  );
});

test("machine store does NOT instantiate its own WebSocket", () => {
  // The transport moved to ``stores/servoThread.js`` — a
  // regression that brings it back into the cross-module
  // store would re-bloat the file to ~700 lines and break the
  // runtime split. The tripwire lives here so the new file
  // owns it.
  const text = readModule();
  assert.doesNotMatch(
    text,
    /new\s+WebSocket\s*\(/,
    "stores/machine.js must not own the WebSocket — use stores/servoThread.js",
  );
  assert.match(
    text,
    /useServoThreadStore\s*\(/,
    "stores/machine.js must compose useServoThreadStore",
  );
});

test("App.vue does not consult a registry for the machine domain", () => {
  // The machine domain is a hard dependency; the shell mounts the
  // base-thread store eagerly so the WebSocket telemetry has its
  // consumer wired by the time any panel mounts. There is no
  // ``registry`` lookup anywhere in the shell.
  const appPath = resolve(repoRoot, "frontend/src/App.vue");
  const source = readFileSync(appPath, "utf-8");
  assert.doesNotMatch(
    source,
    /registry\.modules\.has\(\s*['"]machine['"]\s*\)/,
    "App.vue must not consult the registry for the machine domain (it is a hard dependency)",
  );
  assert.doesNotMatch(source, /import\s+registry\b/);
});