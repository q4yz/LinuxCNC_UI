// A routine (homing, Z tilt, bed mesh, PROBE_ACCURACY, macros) sends MDI
// lines one by one: each one briefly runs the interpreter. That used to
// show as "Running" — the program card hid its file list (it changed
// size) and the console filled with Idle ↔ Running. MDI activity is now
// "Busy"; only a program (AUTO mode) is "Running". The header holds Busy
// a moment so a routine logs one transition each way. And the backend's
// own messages arrive as {"type": "console"} frames.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createPinia, setActivePinia } from "pinia";

import { SystemState, TASK_MODE, INTERP_STATE, useMachineStore } from "../src/stores/stateFacade";
import { emitBackendConsole } from "../src/core/backendConsole";

const src = resolve(dirname(fileURLToPath(import.meta.url)), "../src");

function stateFor(task_mode: number, interp_state: number): string {
  setActivePinia(createPinia());
  const store = useMachineStore();
  store.connectionStatus = "connected";
  store.status = { ...store.status, task_state: 4, estop: 0, task_mode, interp_state, file: "" };
  return store.systemState;
}

test("MDI and manual activity is Busy, a program in AUTO is Running", () => {
  assert.equal(stateFor(TASK_MODE.MDI, INTERP_STATE.READING), SystemState.BUSY);
  assert.equal(stateFor(TASK_MODE.MDI, INTERP_STATE.WAITING), SystemState.BUSY);
  assert.equal(stateFor(TASK_MODE.AUTO, INTERP_STATE.READING), SystemState.RUNNING);
  assert.equal(stateFor(TASK_MODE.MDI, INTERP_STATE.IDLE), SystemState.IDLE);
});

test("the program card only reacts to a program run", () => {
  const widget = readFileSync(resolve(src, "components/ActivePrintWidget.vue"), "utf-8");
  assert.doesNotMatch(widget, /SystemState\.BUSY/);
});

test("the header holds Busy before going back to Idle", () => {
  const header = readFileSync(resolve(src, "components/EStopHeader.vue"), "utf-8");
  assert.match(header, /const BUSY_HOLD_MS = \d+/);
  assert.match(header, /systemState\.value === 'Busy' && \(next === 'Idle' \|\| next === 'Loaded'\)/);
});

test("backend console frames land at their level", () => {
  const seen: Array<[string, string]> = [];
  const store = {
    debug: (t: string) => seen.push(["debug", t]),
    info: (t: string) => seen.push(["info", t]),
    warning: (t: string) => seen.push(["warning", t]),
    error: (t: string) => seen.push(["error", t]),
  } as never;
  emitBackendConsole(store, { level: "debug", text: "PROBE_ACCURACY: sample 1/10 at Z 0.010000" });
  emitBackendConsole(store, { level: "info", text: "PROBE_ACCURACY results" });
  emitBackendConsole(store, { level: "error", text: "aborted" });
  emitBackendConsole(store, { level: "info" });
  emitBackendConsole(store, null);
  assert.deepEqual(seen.map(([l]) => l), ["debug", "info", "error"]);
});
