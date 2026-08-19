// Servo-thread store behavioural tests.
//
// Run with: node --test frontend/tests/test-servo-thread.mjs
//
// The servo-thread store owns the 10 Hz ``/ws/telemetry`` WebSocket
// transport + the time-critical reactive state (``status``,
// ``connectionStatus``, ``errors``, ``isUpdating``). The machine
// module composes this store for telemetry; this suite pins the
// contract the module store depends on:
//
//   * The store opens the socket on ``start()`` and re-connects
//     with a 2 s back-off on close.
//   * ``full_state`` / ``delta`` / ``error`` payloads dispatch
//     to the right handlers and mirror into the State Facade.
//   * ``payload.type === "error"`` routes through
//     ``useConsoleStore().error(...)`` with ``popup: true`` — the
//     silent-bug regression guard.
//   * Historical errors on ``full_state`` replay through the
//     console store so a reconnecting operator sees the backlog.
//   * The store is the single source of truth for the WebSocket
//     transport — ``modules/machine/store.js`` must NOT contain
//     ``new WebSocket(`` after the servo/base split.

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

test("servo-thread store exposes connectionStatus + errors + isUpdating as refs", () => {
  const text = readServo();
  assert.match(text, /const\s+connectionStatus\s*=\s*ref\(\s*['"]disconnected['"]\s*\)/);
  assert.match(text, /const\s+isUpdating\s*=\s*ref\(\s*false\s*\)/);
  assert.match(text, /const\s+errors\s*=\s*ref\(\s*\[\s*\]\s*\)/);
});

test("servo-thread store opens /ws/telemetry and re-uses wsUrl with a 2 s back-off", () => {
  const text = readServo();
  // The store owns the ``new WebSocket(wsUrl)`` call.
  assert.match(text, /\/ws\/telemetry/);
  assert.match(text, /new\s+WebSocket\s*\(\s*wsUrl\s*\)/);
  // 2 s reconnect back-off — see LESSONS_LEARNED § 2.5-style
  // cadence commentary.
  assert.match(text, /reconnectTimer\s*=\s*setTimeout\([\s\S]*?connect\(\s*\)/);
  assert.match(text, /RECONNECT_DELAY_MS\s*=\s*2_000/);
});

test("servo-thread start() / stop() are idempotent", () => {
  const text = readServo();
  // ``start()`` short-circuits if a socket is already in flight;
  // ``stop()`` clears the reconnect timer before closing so the
  // async ``onclose`` cannot schedule a reconnect during teardown.
  assert.match(text, /if\s*\(\s*socket\s*\)\s*return/);
  assert.match(text, /shouldReconnect\s*=\s*false/);
  assert.match(text, /socket\s*=\s*null/);
});

test("servo-thread mirrors the live state into the State Facade on every frame", () => {
  const text = readServo();
  // The State Facade (``stores/stateFacade.js``) is the consumer
  // surface for widgets that just need the high-resolution state
  // vocabulary. Every payload branch must call ``updateStatus``
  // so ``systemState`` / ``printProgress`` / etc. stay current.
  assert.match(text, /payload\.type\s*===\s*["']full_state["']/);
  assert.match(text, /payload\.type\s*===\s*["']delta["']/);
  assert.match(text, /updateStatus\s*\(/);
});

test("servo-thread routes LinuxCNC WS errors through the console store with popup", () => {
  // Regression guard for the silent-bug where the WebSocket
  // ``error`` branch only logged to the browser devtools console
  // (console.error) instead of routing through ``useConsoleStore()``,
  // so the operator's ``ConsolePanel`` never saw the row and the
  // toast never fired. ``popup: true`` is required because
  // ``core/console.js`` short-circuits ``_emitToast`` when the
  // flag is missing.
  const text = readServo();
  assert.match(
    text,
    /payload\.type === "error"[\s\S]*?useConsoleStore\(\)\.error\([\s\S]*?popup:\s*true/,
    "the WS error branch must call useConsoleStore().error() with popup:true",
  );
});

test("servo-thread replays full_state errors through the console store", () => {
  // The backend keeps a bounded error history on ``SharedMachineState``
  // and ships it on ``full_state``. The frontend replays those
  // entries through ``useConsoleStore().error()`` so the operator's
  // ``ConsolePanel`` shows the backlog on reload / reconnect.
  const text = readServo();
  assert.match(
    text,
    /payload\.type === "full_state"[\s\S]*?useConsoleStore\(\)\.error\([\s\S]*?popup:\s*true/,
    "the full_state branch must replay historical errors via useConsoleStore",
  );
});

test("servo-thread store exposes a send() action for inbound WS commands", () => {
  // The /ws/telemetry channel is now bidirectional. The
  // machine module's ``jogContinuous`` calls ``servo.send({type:
  // "jog_keepalive", ...})`` every 250 ms instead of POSTing to
  // ``/api/v1/modules/machine/jog/keepalive`` — the new action
  // is the difference between 4 RTT/s/axis and zero.
  const text = readServo();
  // Action declaration.
  assert.match(text, /function\s+send\s*\(/);
  // No-op guard when the socket isn't open.
  assert.match(text, /socket\.readyState\s*!==\s*WebSocket\.OPEN/);
  // Public surface returns the action.
  assert.match(text, /\bsend\s*,/);
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
    /mirrorToFacade\s*\(\s*\)\s*:\s*void/,
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
  assert.doesNotMatch(
    text,
    /store\.\$state/,
    "DebugPanel must NOT read store.$state (no longer carries telemetry)",
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

test("App.vue does not boot the servo thread from the shell (machine module owns it)", () => {
  // The machine module is a hard dependency; its ``onLoad``
  // opens the WebSocket via ``useServoThreadStore().start()``. The
  // shell no longer needs a fallback boot because the module is
  // always present at runtime. See ``.agent/STATE.md`` § 7 for
  // the modules-are-mandatory rule.
  const appPath = resolve(repoRoot, "frontend/src/App.vue");
  const source = readFileSync(appPath, "utf-8");
  assert.doesNotMatch(
    source,
    /registry\.modules\.has\(\s*['"]machine['"]\s*\)/,
    "App.vue must not consult the registry for the machine module (it is a hard dependency)",
  );
  // The shell does not call ``servoThread.start()`` itself any
  // more — the machine module owns the boot path. ``start()``
  // would have been a double-socket if the module were also
  // present.
  assert.doesNotMatch(
    source,
    /servoThread\.start\s*\(/,
    "App.vue must not call servoThread.start() (the machine module owns it)",
  );
});