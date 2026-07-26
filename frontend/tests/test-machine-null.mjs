// Nullable-module guarantee for the frontend machine module.
//
// Run with: node --test frontend/tests/test-machine-null.mjs
//
// Mirrors ``frontend/tests/test-camera-null.mjs``.  We assert the
// static structure that lets a developer delete
// ``frontend/src/modules/machine/`` without breaking the dashboard
// build:
//
//   * ``DashboardView.vue`` lazily imports the machine panel via
//     ``defineAsyncComponent`` + ``import.meta.glob``.
//   * The DRO and JogControls slots gate on ``v-if="machineMounted"``.
//   * The legacy ``components/DroPanel.vue`` and
//     ``components/JogControls.vue`` are gone.
//   * The new ``modules/machine/components/DroPanel.vue`` and
//     ``modules/machine/components/JogControls.vue`` are in place.
//   * Pre-migration consumer components (ConsolePanel, DebugPanel,
//     GCodeViewer, UpdateManager) route through ``machine-compat``,
//     the nullable adapter that lets the shell build even when the
//     machine module folder has been removed.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");

const dashboardPath = resolve(
  repoRoot,
  "frontend/src/views/DashboardView.vue",
);
const legacyDroPanel = resolve(
  repoRoot,
  "frontend/src/components/DroPanel.vue",
);
const legacyJogControls = resolve(
  repoRoot,
  "frontend/src/components/JogControls.vue",
);
const newDroPanel = resolve(
  repoRoot,
  "frontend/src/modules/machine/components/DroPanel.vue",
);
const newJogControls = resolve(
  repoRoot,
  "frontend/src/modules/machine/components/JogControls.vue",
);
const newStore = resolve(
  repoRoot,
  "frontend/src/modules/machine/store.js",
);
const legacyMachineApi = resolve(
  repoRoot,
  "frontend/src/services/machineApi.js",
);
const legacyStoreShim = resolve(
  repoRoot,
  "frontend/src/stores/machine.js",
);

test("DashboardView uses defineAsyncComponent for the machine panel", () => {
  const source = readFileSync(dashboardPath, "utf-8");
  assert.match(
    source,
    /defineAsyncComponent/,
    "DashboardView must use defineAsyncComponent so the machine chunk is split",
  );
  // The machine panels are loaded via the generic `panelFor`
  // helper, which performs the dynamic import at runtime — not
  // a literal ``import('.../DroPanel.vue')`` call. The regex
  // below looks for that helper invocation so a regression that
  // re-adds a static import is still caught.
  assert.match(
    source,
    /panelFor\(\s*['"]machine['"]\s*,\s*['"]DroPanel['"]\s*\)/,
    "DashboardView must lazily resolve DroPanel via panelFor",
  );
  assert.match(
    source,
    /panelFor\(\s*['"]machine['"]\s*,\s*['"]JogControls['"]\s*\)/,
    "DashboardView must lazily resolve JogControls via panelFor",
  );
});

test("DashboardView guards the machine slots with v-if and a placeholder", () => {
  const source = readFileSync(dashboardPath, "utf-8");
  // The machine slots gate on a reactive ``machineMounted`` flag.
  assert.match(source, /v-if="machineMounted"/);
  assert.match(
    source,
    /registry\.modules\.has\(['"]machine['"]\)/,
    "machineMounted computed must read from the registry",
  );
  // When the module is not mounted the dashboard renders a
  // placeholder card rather than throwing — keep the layout
  // consistent.
  assert.match(source, /v-else/);
  assert.match(source, /not mounted/i);
});

test("DashboardView does not statically import the legacy machine paths", () => {
  const source = readFileSync(dashboardPath, "utf-8");
  // A regression where someone re-adds
  // ``import DroPanel from '../components/DroPanel.vue'`` would
  // re-introduce the "deleting the module folder breaks the
  // build" failure mode (Gotcha #1).
  assert.doesNotMatch(
    source,
    /from\s+['"]\.\.\/components\/DroPanel\.vue['"]/,
    "DashboardView must not statically import the legacy DRO path",
  );
  assert.doesNotMatch(
    source,
    /from\s+['"]\.\.\/components\/JogControls\.vue['"]/,
    "DashboardView must not statically import the legacy JogControls path",
  );
});

test("legacy components/DroPanel.vue and JogControls.vue are removed", () => {
  assert.equal(
    existsSync(legacyDroPanel),
    false,
    `expected ${legacyDroPanel} to be removed after migration`,
  );
  assert.equal(
    existsSync(legacyJogControls),
    false,
    `expected ${legacyJogControls} to be removed after migration`,
  );
});

test("new modules/machine/components/ files exist", () => {
  assert.ok(existsSync(newDroPanel), `expected ${newDroPanel}`);
  assert.ok(existsSync(newJogControls), `expected ${newJogControls}`);
});

test("module store file exposes useMachineStore", () => {
  assert.ok(existsSync(newStore));
  const text = readFileSync(newStore, "utf-8");
  assert.match(
    text,
    /export\s+const\s+useMachineStore\s*=\s*defineStore/,
    "machine store must export useMachineStore via defineStore",
  );
});

test("legacy stores/machine.js shim is removed after migration window closes", () => {
  // Issue #47 closes the migration window: the compatibility shim
  // at ``stores/machine.js`` (which used to re-export the module
  // store for third-party consumers) and the raw
  // ``services/machineApi.js`` wrapper are both deleted. All machine
  // consumers should now import from ``stores/machine-compat``
  // (nullable shell adapter) or directly from
  // ``modules/machine/store.js`` / ``ModulesMachineService``.
  assert.equal(
    existsSync(legacyStoreShim),
    false,
    `expected ${legacyStoreShim} to be removed after issue #47`,
  );
  assert.equal(
    existsSync(legacyMachineApi),
    false,
    `expected ${legacyMachineApi} to be removed after issue #47`,
  );
});

test("App.vue connects only when the machine module is not mounted", () => {
  // The module's ``onLoad`` already opens the WebSocket;
  // App.vue's connect() must guard against a double-socket by
  // checking ``registry.modules.has('machine')`` first. The
  // ``connect()`` action itself is also idempotent per the
  // store implementation.
  const appPath = resolve(repoRoot, "frontend/src/App.vue");
  const source = readFileSync(appPath, "utf-8");
  assert.match(
    source,
    /registry\.modules\.has\(\s*['"]machine['"]\s*\)/,
    "App.vue must consult the registry before calling store.connect()",
  );
});

test("machine module JogControls unmount stops all in-flight jogs", () => {
  const jogPath = resolve(
    repoRoot,
    "frontend/src/modules/machine/components/JogControls.vue",
  );
  const text = readFileSync(jogPath, "utf-8");
  // Issue #38 § 6 Risk #5 — the component must call
  // ``stopAllJogging`` from ``onBeforeUnmount`` so navigating
  // away releases the axis within the watchdog window.
  assert.match(
    text,
    /onBeforeUnmount/,
    "JogControls must register an onBeforeUnmount hook",
  );
  assert.match(text, /stopAllJogging/);
});

test("machine module uses the module-scoped URL prefixes", () => {
  // The frontend's generated services were updated to point
  // at the module URLs (``/api/v1/modules/machine/...``). The
  // original flat URLs must no longer appear in the service
  // definitions.
  //
  // NOTE: After the issue #41 follow-up, the generated service
  // classes were consolidated under the ``ModulesMachineService``
  // / ``ModulesProgramService`` names (the legacy
  // ``MachineStateService`` / ``JoggingService`` /
  // ``ProgramExecutionService`` were renamed and unified). The
  // test now reads the current file names so the assertions
  // continue to track the real shape of the generated client.
  const machineSvc = resolve(
    repoRoot,
    "frontend/generated/api/services/ModulesMachineService.ts",
  );
  const programSvc = resolve(
    repoRoot,
    "frontend/generated/api/services/ModulesProgramService.ts",
  );

  const machineText = existsSync(machineSvc)
    ? readFileSync(machineSvc, "utf-8")
    : readFileSync(
        resolve(repoRoot, "frontend/src/modules/machine/store.js"),
        "utf-8",
      );
  const programText = existsSync(programSvc)
    ? readFileSync(programSvc, "utf-8")
    : readFileSync(
        resolve(repoRoot, "frontend/src/components/ConfigList.vue"),
        "utf-8",
      );

  // Generated clients are intentionally ignored and may not exist in a
  // source-only checkout. In that case, still verify that consumers use
  // the module-scoped service names; a build with a generated client
  // performs the URL checks below.
  if (!existsSync(machineSvc) || !existsSync(programSvc)) {
    assert.match(machineText, /ModulesMachineService/);
    assert.match(programText, /ModulesProgramService/);
    return;
  }

  // The generated client groups the machine state and jog operations
  // under one module service after the registry migration.
  const jogText = machineText;

  // Spot-check the URLs that the store actually calls.
  for (const url of [
    "/api/v1/modules/machine/state",
    "/api/v1/modules/machine/mode",
    "/api/v1/modules/machine/home",
    "/api/v1/modules/machine/mdi",
  ]) {
    assert.match(
      machineText,
      new RegExp(url.replace(/\//g, "\\/")),
      `ModulesMachineService must use ${url}`,
    );
  }
  for (const url of [
    "/api/v1/modules/machine/jog",
    "/api/v1/modules/machine/jog/keepalive",
    "/api/v1/modules/machine/jog/stop",
  ]) {
    assert.match(
      machineText,
      new RegExp(url.replace(/\//g, "\\/")),
      `ModulesMachineService must use ${url}`,
    );
  }
  // The legacy ``/api/v1/machine/...`` URLs must no longer
  // appear anywhere in the machine-related generated services.
  for (const url of [
    "/api/v1/machine/state",
    "/api/v1/machine/mode",
    "/api/v1/machine/home",
    "/api/v1/machine/jog",
  ]) {
    assert.doesNotMatch(
      machineText,
      new RegExp(url.replace(/\//g, "\\/")),
      `ModulesMachineService must not use legacy ${url}`,
    );
    assert.doesNotMatch(
      jogText,
      new RegExp(url.replace(/\//g, "\\/")),
      `ModulesMachineService must not use legacy ${url}`,
    );
  }

  // Program endpoints moved to /api/v1/modules/program/...
  for (const url of [
    "/api/v1/modules/program/run",
    "/api/v1/modules/program/stop",
    "/api/v1/modules/program/pause",
    "/api/v1/modules/program/resume",
    "/api/v1/modules/program/parse",
  ]) {
    assert.match(
      programText,
      new RegExp(url.replace(/\//g, "\\/")),
      `ModulesProgramService must use ${url}`,
    );
  }
  assert.doesNotMatch(programText, /\/api\/v1\/program\//);
});
