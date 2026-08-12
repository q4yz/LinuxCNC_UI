// Static-structure tests for the Issue #60 State Facade store.
//
// Run with: node --test frontend/tests/test-machine-facade.mjs
//
// Pinia is not available in a bare ``node --test`` environment, so
// this suite asserts the source matches the spec from the issue:
//
//   * ``TASK_STATE`` and ``INTERP_STATE`` constants carry the exact
//     integer values the backend's ``hardware/linuxcnc_mock.py``
//     uses.
//   * The ``SystemState`` enum exposes the eight members the issue
//     requires.
//   * The ``systemState`` getter implements the priority chain:
//     Offline > Updating > Estop > PowerOff > Paused/Running/Idle.
//   * ``printProgress`` collapses to 0 for missing / zero total lines
//     and clamps at 100.
//   * ``isEstopActive`` is true whenever ``estop == 1`` or
//     ``task_state == TASK_STATE.ESTOP``.
//   * The store exposes an ``updateStatus`` action and a mocked
//     ``recentFiles`` getter per the issue's "mock for now" note.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");

const facadePath = resolve(
  repoRoot,
  "frontend/src/stores/stateFacade.js",
);

function readFacade() {
  return readFileSync(facadePath, "utf-8");
}

test("facade file exists", () => {
  // The whole rest of the suite is moot if the file is missing.
  assert.ok(
    readFileSync(facadePath, "utf-8").length > 0,
    "expected frontend/src/stores/stateFacade.js to exist",
  );
});

test("facade exports TASK_STATE with the exact integer values from LinuxCNC", () => {
  const text = readFacade();
  assert.match(
    text,
    /export\s+const\s+TASK_STATE\s*=\s*Object\.freeze\(\s*\{[\s\S]*?ESTOP:\s*1/,
  );
  assert.match(text, /ESTOP_RESET:\s*2/);
  assert.match(text, /OFF:\s*3/);
  assert.match(text, /ON:\s*4/);
});

test("facade exports INTERP_STATE with the exact integer values from LinuxCNC", () => {
  const text = readFacade();
  assert.match(
    text,
    /export\s+const\s+INTERP_STATE\s*=\s*Object\.freeze\(\s*\{[\s\S]*?IDLE:\s*1/,
  );
  assert.match(text, /READING:\s*2/);
  assert.match(text, /PAUSED:\s*3/);
  assert.match(text, /WAITING:\s*4/);
});

test("facade exports SystemState enum with all eight members", () => {
  const text = readFacade();
  assert.match(
    text,
    /export\s+const\s+SystemState\s*=\s*Object\.freeze\(\s*\{/,
  );
  for (const member of [
    "OFFLINE",
    "UPDATING",
    "ESTOP",
    "POWER_OFF",
    "IDLE",
    "LOADED",
    "RUNNING",
    "PAUSED",
    "FAILURE",
  ]) {
    assert.match(
      text,
      new RegExp(`${member}:\\s*"`),
      `SystemState.${member} must exist`,
    );
  }
});

test("facade defines systemState getter with the documented priority chain", () => {
  const text = readFacade();
  assert.match(text, /systemState\s*\(\s*state\s*\)\s*\{/);
  // 1. Offline / Updating connection-level overrides.
  assert.match(text, /connectionStatus\s*!==\s*["']connected["']/);
  assert.match(text, /SystemState\.OFFLINE/);
  assert.match(text, /SystemState\.UPDATING/);
  // 2. Safety override.
  assert.match(text, /SystemState\.ESTOP/);
  // 3. Power-off chain.
  assert.match(text, /SystemState\.POWER_OFF/);
  // 4. Execution chain.
  assert.match(text, /SystemState\.PAUSED/);
  assert.match(text, /SystemState\.RUNNING/);
  assert.match(text, /SystemState\.LOADED/, "LOADED member must be present");
  assert.match(text, /SystemState\.IDLE/);
  // 5. Failure fallback.
  assert.match(text, /SystemState\.FAILURE/);
});

test("facade exposes printProgress that collapses on zero/missing totals and clamps at 100", () => {
  const text = readFacade();
  assert.match(text, /printProgress\s*\(\s*state\s*\)\s*\{/);
  // Collapse to 0 when total_lines is missing or 0.
  assert.match(
    text,
    /total\s*<=\s*0/,
    "printProgress must collapse to 0 when total_lines is 0",
  );
  // Clamp at 100 to avoid the bar overshooting the wrapper.
  assert.match(
    text,
    /Math\.min\(\s*100/,
    "printProgress must clamp at 100%",
  );
});

test("facade exposes isEstopActive covering both raw safety signals", () => {
  const text = readFacade();
  assert.match(text, /isEstopActive\s*\(\s*state\s*\)\s*\{/);
  assert.match(text, /estop\s*===\s*1/);
  assert.match(text, /TASK_STATE\.ESTOP/);
});

test("facade ships a mocked recentFiles getter with the FileInfo shape", () => {
  const text = readFacade();
  assert.match(text, /recentFiles\s*\(\s*\)\s*\{/);
  // Each entry exposes ``filename`` so the widget can render without
  // changes when the real backend list lands.
  assert.match(text, /filename:/);
  assert.match(text, /modified:/);
});

test("facade defines updateStatus action that mutates the raw state", () => {
  const text = readFacade();
  assert.match(
    text,
    /updateStatus\s*\(\s*newPayload\s*\)\s*\{/,
    "updateStatus must accept a payload object",
  );
  // The action must touch all three flags the transport cares about.
  assert.match(text, /this\.connectionStatus\s*=/);
  assert.match(text, /this\.isUpdating\s*=/);
  assert.match(text, /this\.status\s*=/);
});

test("facade is registered as a Pinia store via defineStore", () => {
  const text = readFacade();
  assert.match(
    text,
    /export\s+const\s+useMachineStore\s*=\s*defineStore\(\s*["']machineStore["']/,
  );
  assert.match(text, /state:\s*\(\s*\)\s*=>\s*\(/);
  assert.match(text, /getters:\s*\{/);
  assert.match(text, /actions:\s*\{/);
});

test("servo-thread store forwards telemetry to the facade on every WS message", () => {
  // The facade is useless in production unless the servo-thread
  // store (which owns the WebSocket) calls ``updateStatus`` on
  // every ``full_state`` / ``delta`` payload. The machine module
  // store composes the servo thread; it does not import the
  // facade directly.
  const servoPath = resolve(
    repoRoot,
    "frontend/src/stores/servoThread.js",
  );
  const text = readFileSync(servoPath, "utf-8");
  // Import the facade from the servo-thread store.
  assert.match(
    text,
    /import\s*\{[^}]*useMachineStore[^}]*\}\s*from\s*["']\.\/stateFacade\.js["']/,
  );
  // Forward on the full_state and delta branches via the
  // mirror helper.
  assert.match(text, /useFacadeStore\s*\(/);
  assert.match(text, /payload\.type\s*===\s*["']full_state["']/);
  assert.match(text, /payload\.type\s*===\s*["']delta["']/);
});

test("ActivePrintWidget binds to the facade store (systemState getter)", () => {
  // The widget must consume the facade — not the legacy compat
  // shim — so the State Facade actually drives the dashboard.
  const widgetPath = resolve(
    repoRoot,
    "frontend/src/components/ActivePrintWidget.vue",
  );
  const text = readFileSync(widgetPath, "utf-8");
  assert.match(
    text,
    /import\s*\{[^}]*useMachineStore[^}]*\}\s*from\s*["'][^"']*stores\/stateFacade\.js["']/,
  );
  assert.match(text, /systemState/);
  // No legacy compat-shim import — the widget reads from the
  // runtime stores layer (``stores/machine.js`` /
  // ``stores/stateFacade.js``) instead.
  assert.doesNotMatch(text, /machineStoreShim/);
  assert.doesNotMatch(text, /machine-compat/);
});

test("machine store no longer owns the WebSocket transport", () => {
  // The 10 Hz ``/ws/telemetry`` socket lives in
  // ``stores/servoThread.js``; the cross-module machine store
  // composes it. A regression that brings the socket back into
  // ``stores/machine.js`` would re-bloat the file to ~700 lines
  // and break the runtime split.
  const modulePath = resolve(
    repoRoot,
    "frontend/src/stores/machine.js",
  );
  const text = readFileSync(modulePath, "utf-8");
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

test("ActivePrintWidget mocks Print/Pause/Resume/Stop click handlers", () => {
  const widgetPath = resolve(
    repoRoot,
    "frontend/src/components/ActivePrintWidget.vue",
  );
  const text = readFileSync(widgetPath, "utf-8");
  // The widget defines one handler per action; every handler
  // emits a debug log via the console store (not a raw
  // ``console.log``) so the operator sees the request in the
  // panel. The handlers also delegate to the generated program
  // service (``runProgram`` / ``pauseProgram`` / ``resumeProgram``
  // / ``stopProgram``). The two-step lifecycle is reflected here:
  // ``loadFile`` calls ``loadProgram`` (the "load" step) and the
  // ``Loaded`` branch adds a dedicated ``startLoadedProgram``
  // handler that calls ``runProgram``.
  for (const handler of [
    "loadFile",
    "startLoadedProgram",
    "unloadProgram",
    "pausePrint",
    "resumePrint",
    "stopPrint",
  ]) {
    assert.match(text, new RegExp(`function\\s+${handler}\\b`));
  }
  for (const serviceCall of [
    "loadProgram",
    "runProgram",
    "pauseProgram",
    "resumeProgram",
    "stopProgram",
  ]) {
    assert.match(text, new RegExp(`ModulesProgramService\\.${serviceCall}\\b`));
  }
  // The widget must host three top-level lifecycle branches
  // (Standby / Loaded / Active). The file list is now always
  // visible — the branches only carry the lifecycle-specific
  // hint text. ``!isActive`` appears in the Standby branch's
  // ``v-if`` (sometimes combined with ``!isLoaded``); the Loaded
  // branch uses ``v-else-if="isLoaded"``; the Active branch uses
  // ``v-else``. We do simple substring checks for the three
  // directives — robust to CRLF + multiline attribute quirks.
  assert.match(
    text,
    /v-if\s*=\s*["'][^"']*!isActive[^"']*["']/,
    "Standby branch (v-if with !isActive) must be present",
  );
  assert.match(
    text,
    /v-else-if\s*=\s*["']isLoaded["']/,
    "Loaded branch (v-else-if=\"isLoaded\") must be present",
  );
  assert.match(text, /v-else/);
  // ``consoleStore.debug`` drives the operator log trail.
  assert.match(text, /consoleStore\.debug\(/);
});

test("FileManager routes the edit action into the routed EditorView", () => {
  const fmPath = resolve(
    repoRoot,
    "frontend/src/components/FileManager.vue",
  );
  const text = readFileSync(fmPath, "utf-8");
  // Issue #132: ``editFile`` delegates to ``openInEditor`` which
  // pushes ``/editor?source=programs&name=<file>``. The store is
  // no longer touched here — routing is source-driven and the
  // universal editor owns the load/save lifecycle.
  assert.match(text, /function\s+editFile\b/);
  assert.match(text, /openInEditor\(/);
  assert.match(text, /source:\s*['"]programs['"]/);
  assert.match(text, /name:\s*filename/);
});

test("FilesView forwards every edit-event argument to App.vue", () => {
  const fvPath = resolve(
    repoRoot,
    "frontend/src/views/FilesView.vue",
  );
  const text = readFileSync(fvPath, "utf-8");
  // ``handleEdit`` must use a rest parameter so mode/content survive.
  assert.match(text, /function\s+handleEdit\s*\(\s*\.\.\.\s*args\s*\)/);
  assert.match(text, /emit\(\s*['"]edit['"]\s*,\s*\.\.\.\s*args\s*\)/);
});

test("FileManager wraps its content in a full-page w-full h-full flex flex-col container", () => {
  // Issue #60 refactor: FileManager must be a full-page view, not a
  // dashboard card. The outermost wrapper must declare h-full and
  // w-full so it stretches edge-to-edge inside FilesView; the inner
  // scrollable body uses ``flex-1`` so the file list grows to fill
  // the remaining vertical space without overflowing the header.
  const fmPath = resolve(
    repoRoot,
    "frontend/src/components/FileManager.vue",
  );
  const text = readFileSync(fmPath, "utf-8");
  // Outermost wrapper — full width and height, flex column so the
  // header stays put and the file list scrolls.
  assert.match(
    text,
    /class\s*=\s*["'][^"']*w-full[^"']*h-full[^"']*flex[^"']*flex-col[^"']*["']/,
  );
  // The scrollable body uses ``flex-1`` so it grows to fill the
  // leftover space. The companion ``overflow-y-auto`` keeps the
  // list scrollable; ``min-h-0`` is no longer required because
  // the body sits inside a flex column with an explicit height.
  assert.match(text, /flex-1[^"']*overflow-y-auto/);
});

test("ActivePrintWidget reads progress from the base-thread store", () => {
  // The dashboard's progress bar now reads from the shared
  // ``baseThread`` facade store — one 1 Hz REST poll feeds every
  // slow-data consumer. The widget must:
  //
  //   * import ``useBaseThreadStore`` and destructure the
  //     ``progress`` ref via ``storeToRefs``,
  //   * bind the template to ``progress.current_line`` /
  //     ``progress.total_lines`` (the polled values, not the
  //     legacy WebSocket fields),
  //   * NOT own its own ``setInterval`` / ``clearInterval`` —
  //     that's the base-thread store's job.
  const widgetPath = resolve(
    repoRoot,
    "frontend/src/components/ActivePrintWidget.vue",
  );
  const text = readFileSync(widgetPath, "utf-8");
  assert.match(text, /useBaseThreadStore\s*\(/);
  assert.match(
    text,
    /const\s*\{\s*progress\s*\}\s*=\s*storeToRefs\s*\(\s*baseThread\s*\)/,
  );
  assert.match(text, /\{\{\s*progress\.current_line\s*\}\}/);
  assert.match(
    text,
    /\{\{\s*progress\.total_lines[^}]*\}\}/,
    "template must render the polled total_lines (with '?' fallback)",
  );
  // The widget must NOT own a polling interval — the base-thread
  // store owns that. ``onBeforeUnmount`` was used to clear the
  // legacy interval and must be gone now too.
  assert.doesNotMatch(text, /setInterval\s*\(\s*pollProgress/);
  assert.doesNotMatch(text, /clearInterval\s*\(\s*progressPollHandle/);
  assert.doesNotMatch(text, /onBeforeUnmount\s*\(/);
  assert.doesNotMatch(text, /ModulesProgramService\.getProgramProgress\s*\(/);
});