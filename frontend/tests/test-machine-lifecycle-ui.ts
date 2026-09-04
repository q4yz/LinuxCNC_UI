// Structural guard for the machine-lifecycle UI.
//
// "Select as main" persists a default machine in the backend
// (``machine_config/default_machine.json``); generic "Start machine"
// buttons launch that default's ``machines/<default>/config/machine.ini``.
// The UI surface:
//
//   * ``MachinesExplorer`` — root-level machine folders get ▶ Start
//     (persist + launch) and ★ Set main (persist only) buttons, plus
//     a "main" badge on the current default.
//   * ``UpdateManager`` — Start default machine / Stop machine
//     buttons with a live default-machine status line.
//
// Run with: ``node --test frontend/tests/test-machine-lifecycle-ui.ts``

import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");
const src = resolve(repoRoot, "frontend/src");

const read = (rel) => readFileSync(resolve(src, rel), "utf-8");
const readRepo = (rel) => readFileSync(resolve(repoRoot, rel), "utf-8");

// ------------------------------------------------------------------ //
// Facade                                                                 //
// ------------------------------------------------------------------ //

test("machineLifecycleFacade wraps the system lifecycle routes", () => {
  const path = resolve(src, "facades/machineLifecycleFacade.ts");
  assert.ok(existsSync(path), "facades/machineLifecycleFacade.ts must exist");
  const text = readFileSync(path, "utf-8");

  for (const fn of ["getStatus", "startMachine", "setDefaultMachine", "stopMachine", "getConsoleLog"]) {
    assert.match(text, new RegExp(`static ${fn}\\(`), `facade must define ${fn}()`);
  }

  for (const route of [
    '"/api/v1/system/machine"',
    '"/api/v1/system/machine/start"',
    '"/api/v1/system/machine/default"',
    '"/api/v1/system/machine/stop"',
  ]) {
    assert.match(text, new RegExp(route.replace(/\//g, "\\$&")), `facade must call ${route}`);
  }
  assert.match(
    text,
    /\/api\/v1\/system\/machine\/log/,
    "facade must call the console-log tail route",
  );

  // The generated client is stale (no machine body) — the facade
  // must pass the machine name itself.
  assert.match(
    text,
    /JSON\.stringify\(machine \? \{ machine \} : \{\}\)/,
    "startMachine must send the optional machine body",
  );
  assert.match(
    text,
    /status:\s*response\.status/,
    "HTTP errors must carry .status so callers can special-case 404/409",
  );
});

// ------------------------------------------------------------------ //
// MachinesExplorer                                                       //
// ------------------------------------------------------------------ //

test("MachinesExplorer: root-level folders get Start + Set main", () => {
  const text = read("components/machineconfig/MachinesExplorer.vue");

  // Root-level gate: folders without a parent are machine folders.
  assert.match(
    text,
    /function isMachineFolder\(entry: DirectoryEntryModel\): boolean \{\s*return entry\.kind === "folder" && !entry\.parent;?\s*\}/,
    "buttons must be gated to ROOT-level folders only",
  );
  assert.match(text, /v-if="isMachineFolder\(entry\)"/, "row must gate the lifecycle actions");

  // Actions wire to the facade (persist-default + start semantics).
  assert.match(text, /MachineLifecycleFacade\.startMachine\(entry\.name\)/, "Start must pass the machine name");
  assert.match(text, /MachineLifecycleFacade\.setDefaultMachine\(entry\.name\)/, "Set main must pass the machine name");
  assert.match(text, /MachineLifecycleFacade\.getStatus\(\)/, "badge needs the status poll");

  // "main" badge on the current default.
  assert.match(text, /v-if="defaultMachine === entry\.name"/, "default machine must be badged");
  assert.match(text, /main/, "badge text");

  // In-flight guards + feedback.
  assert.match(text, /startingPath/, "start button needs a per-row loading state");
  assert.match(text, /settingMainPath/, "set-main button needs a per-row loading state");
  assert.match(text, /consoleStore\.(success|warning|error)\(/, "actions must report to the console store");
});

// ------------------------------------------------------------------ //
// UpdateManager                                                          //
// ------------------------------------------------------------------ //

test("UpdateManager adds Start-default-machine and Stop-machine controls", () => {
  const text = read("components/UpdateManager.vue");

  assert.match(text, /data-testid="machine-start-default"/, "start button test id");
  assert.match(text, /data-testid="machine-stop"/, "stop button test id");
  assert.match(text, /data-testid="machine-default-name"/, "status line test id");

  assert.match(
    text,
    /MachineLifecycleFacade\.startMachine\(\)/,
    "Start default machine must call startMachine WITHOUT a machine name",
  );
  assert.match(
    text,
    /MachineLifecycleFacade\.stopMachine\(\)/,
    "Stop machine must call the stop route",
  );
  assert.match(
    text,
    /MachineLifecycleFacade\.getStatus\(\)/,
    "status line must be fed by the facade",
  );

  // 404 guidance points at the Machines explorer.
  assert.match(text, /No default machine selected/, "404 must explain how to fix it");
});

test("UpdateManager opens the console log in the universal read-only editor on start failure", () => {
  const text = read("components/UpdateManager.vue");

  assert.match(text, /data-testid="machine-view-log"/, "must offer an explicit View log button");
  assert.match(
    text,
    /openInEditor\(\{\s*source:\s*EDITOR_SOURCES\.MACHINE_LOG/,
    "View log must open the machine_log source in the universal editor",
  );
  assert.match(text, /readOnly:\s*true/, "the log view must be read-only");
  // A start failure that isn't the well-understood 409/404 cases is
  // most likely a crash — pop the log open automatically instead of
  // leaving the operator to go find it.
  assert.match(
    text,
    /Failed to start machine[\s\S]*?openConsoleLog\(\)/,
    "an unrecognised start failure must auto-open the console log",
  );
});

test("editor store wires machine_log as a read-only source fed by getConsoleLog()", () => {
  const text = read("stores/editor.ts");

  assert.match(text, /MACHINE_LOG:\s*['"]machine_log['"]/, "EDITOR_SOURCES.MACHINE_LOG must be 'machine_log'");
  assert.match(
    text,
    /READ_ONLY_SOURCES = new Set<string>\(\[[\s\S]*?EDITOR_SOURCES\.MACHINE_LOG[\s\S]*?\]\)/,
    "machine_log must be read-only — there is no write endpoint for it",
  );
  assert.match(
    text,
    /case EDITOR_SOURCES\.MACHINE_LOG: return readMachineLogContent\(\)/,
    "dispatchRead must route machine_log to readMachineLogContent",
  );
  assert.match(
    text,
    /MachineLifecycleFacade\.getConsoleLog\(\)/,
    "readMachineLogContent must call the facade's getConsoleLog()",
  );
});

// ------------------------------------------------------------------ //
// Backend contract                                                       //
// ------------------------------------------------------------------ //

test("backend persists a default machine and starts machines/<name>/config/machine.ini", () => {
  const router = readRepo("backend/system/routers/machine_lifecycle.py");
  assert.match(router, /class MachineStartRequest/, "/start must accept an optional body");
  assert.match(router, /payload\.machine/, "/start must forward the machine choice");
  assert.match(router, /@router\.post\(\s*"\/default"/, "POST /default endpoint must exist");
  assert.match(router, /default_machine/, "status must expose the default machine");

  const service = readRepo("backend/system/services/MachineLifecycleService.py");
  assert.match(
    service,
    /config\/machine\.ini/,
    "INI resolution must follow machines/<name>/config/machine.ini",
  );
  assert.match(
    service,
    /default_machine\.json/,
    "the default machine must be persisted as machine_config/default_machine.json",
  );
  assert.match(
    service,
    /def set_default_machine\(/,
    "service must expose the default-machine setter",
  );
  assert.match(
    router,
    /@router\.get\(\s*"\/log"/,
    "GET /log endpoint must exist so the UI can fetch the console-log tail",
  );
  assert.match(
    service,
    /def console_log\(/,
    "service must expose the console-log tail reader",
  );
});
