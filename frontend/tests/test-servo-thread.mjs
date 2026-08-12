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
  "frontend/src/stores/servoThread.js",
);
const modulePath = resolve(
  repoRoot,
  "frontend/src/modules/machine/store.js",
);

function readServo() {
  return readFileSync(servoPath, "utf-8");
}

function readModule() {
  return readFileSync(modulePath, "utf-8");
}

test("servo-thread store file lives at stores/servoThread.js", () => {
  // The whole suite is moot if the file is missing.
  assert.ok(
    readFileSync(servoPath, "utf-8").length > 0,
    "expected frontend/src/stores/servoThread.js to exist",
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

test("machine module store does NOT instantiate its own WebSocket", () => {
  // The transport moved to ``stores/servoThread.js`` — a
  // regression that brings it back into the module store
  // re-bloats the file to ~700 lines and breaks the runtime
  // split. The tripwire lives here so the new file owns it.
  const text = readModule();
  assert.doesNotMatch(
    text,
    /new\s+WebSocket\s*\(/,
    "modules/machine/store.js must not own the WebSocket — use stores/servoThread.js",
  );
  assert.match(
    text,
    /useServoThreadStore\s*\(/,
    "modules/machine/store.js must compose useServoThreadStore",
  );
});

test("App.vue boots the servo thread only when the machine module is absent", () => {
  // The module's ``onLoad`` already opens the WebSocket; the
  // shell's fallback boot must guard against a double-socket.
  const appPath = resolve(repoRoot, "frontend/src/App.vue");
  const source = readFileSync(appPath, "utf-8");
  assert.match(
    source,
    /registry\.modules\.has\(\s*['"]machine['"]\s*\)/,
    "App.vue must consult the registry before starting the servo thread",
  );
  assert.match(
    source,
    /servoThread\.start\(\s*\)/,
    "App.vue must call servoThread.start() when the module is absent",
  );
});