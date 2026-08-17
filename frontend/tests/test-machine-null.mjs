// Machine module structural tests.
//
// Run with: node --import ../scripts/vue-test-loader-register.mjs
//             --test test-machine-null.mjs
//
// Pins the static structure the machine module's components and
// cross-module consumers depend on:
//
//   * ``DashboardView.vue`` statically imports ``DroPanel`` and
//     ``JogControls`` from the module folder (no lazy discovery).
//   * The DRO and JogControls slots gate on
//     ``v-if="machineMounted"``.
//   * The legacy ``components/DroPanel.vue`` and
//     ``components/JogControls.vue`` are gone.
//   * The new ``modules/machine/components/DroPanel.vue`` and
//     ``modules/machine/components/JogControls.vue`` are in place.
//   * The machine store lives at ``stores/machine.js`` (the
//     cross-module runtime layer); the module's ``store.js`` is a
//     thin re-export.
//
// The machine module is a hard dependency. The previous
// nullable-module guarantee was retired in the same refactor that
// deleted ``stores/machineStoreShim.js``; the no-lazy-imports rule
// documented in ``.agent/STATE.md`` § 13 made the lazy-discovery
// scaffolding (``panelFor``, ``defineAsyncComponent``,
// ``import.meta.glob(..., { eager: false })``) obsolete.

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
  "frontend/src/stores/machine.ts",
);
const moduleStoreReexport = resolve(
  repoRoot,
  "frontend/src/modules/machine/store.ts",
);
const legacyMachineApi = resolve(
  repoRoot,
  "frontend/src/services/machineApi.ts",
);
const removedShim = resolve(
  repoRoot,
  "frontend/src/stores/machineStoreShim.ts",
);

test("DashboardView statically imports the machine module panels", () => {
  const source = readFileSync(dashboardPath, "utf-8");
  // The machine module is a hard dependency — its panels must be
  // imported statically. ``panelFor`` and ``defineAsyncComponent``
  // were retired when lazy imports were banned in the contract
  // rewrite (see ``.agent/STATE.md`` § 13).
  assert.doesNotMatch(
    source,
    /panelFor\(\s*['"]machine['"]/,
    "DashboardView must not use the legacy panelFor lazy discovery for the machine module",
  );
  assert.match(
    source,
    /import\s+DroPanelRaw\s+from\s+['"]\.\.\/modules\/machine\/components\/DroPanel\.vue['"]/,
    "DashboardView must statically import DroPanel from the module folder",
  );
  assert.match(
    source,
    /import\s+JogControlsRaw\s+from\s+['"]\.\.\/modules\/machine\/components\/JogControls\.vue['"]/,
    "DashboardView must statically import JogControls from the module folder",
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
  // When the module is excluded by ``MODULES_ENABLED`` the
  // dashboard renders no card. With the no-lazy-imports rule
  // the panel itself is statically imported, so there is no
  // longer a ``v-else`` placeholder — the slot simply hides.
  assert.doesNotMatch(source, /\bv-else\b/);
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

test("stores/machine.js exposes useMachineStore", () => {
  // The machine store body lives in ``stores/machine.js`` (the
  // cross-module runtime layer). The module's own components
  // import via the historical ``../store.js`` re-export.
  assert.ok(existsSync(newStore));
  const text = readFileSync(newStore, "utf-8");
  assert.match(
    text,
    /export\s+const\s+useMachineStore\s*=\s*defineStore/,
    "machine store must export useMachineStore via defineStore",
  );
  // And the module-side re-export file exists.
  assert.ok(existsSync(moduleStoreReexport));
});

test("the removed compat shim is gone", () => {
  // The shim was deleted in the consolidation that moved the
  // machine store to ``stores/machine.js``. The migration window
  // for third-party consumers is closed; the machine module is
  // a hard dependency (same as the temperature module).
  assert.equal(
    existsSync(removedShim),
    false,
    `expected ${removedShim} to be removed`,
  );
  assert.equal(
    existsSync(legacyMachineApi),
    false,
    `expected ${legacyMachineApi} to be removed after issue #47`,
  );
});

test("App.vue does not start the servo thread (machine module owns it)", () => {
  // The machine module is a hard dependency; its ``onLoad``
  // opens the WebSocket via ``useServoThreadStore().start()``.
  // App.vue previously guarded a fallback boot with
  // ``registry.modules.has('machine')``; that path is gone
  // because the module is always present at runtime. See
  // ``.agent/STATE.md`` § 7 for the modules-are-mandatory rule.
  const appPath = resolve(repoRoot, "frontend/src/App.vue");
  const source = readFileSync(appPath, "utf-8");
  assert.doesNotMatch(
    source,
    /registry\.modules\.has\(\s*['"]machine['"]\s*\)/,
    "App.vue must not consult the registry for the machine module (it is a hard dependency)",
  );
  assert.doesNotMatch(
    source,
    /servoThread\.start\s*\(/,
    "App.vue must not call servoThread.start() (the machine module owns it)",
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
  // at the module URLs. After the state-module extraction,
  // ``ModulesAxisService`` only carries the ``/home`` endpoint
  // (homing is an axis-motion action); ``/state``, ``/mode``,
  // and ``/mdi`` live in the separate state module exposed as
  // ``ModulesMachineStateService`` under
  // ``/api/v1/modules/machine_state/...``. The original flat
  // ``/api/v1/machine/...`` URLs must no longer appear in the
  // service definitions. Jog goes over the ``/ws/telemetry``
  // WebSocket exclusively, so the historical ``/jog``,
  // ``/jog/keepalive``, and ``/jog/stop`` REST URLs are no
  // longer asserted here.
  const axisSvc = resolve(
    repoRoot,
    "frontend/generated/api/services/ModulesAxisService.ts",
  );
  const stateSvc = resolve(
    repoRoot,
    "frontend/generated/api/services/ModulesMachineStateService.ts",
  );
  const programSvc = resolve(
    repoRoot,
    "frontend/generated/api/services/ModulesProgramService.ts",
  );

  const axisText = existsSync(axisSvc)
    ? readFileSync(axisSvc, "utf-8")
    : readFileSync(
        resolve(repoRoot, "frontend/src/modules/machine/store.ts"),
        "utf-8",
      );
  const stateText = existsSync(stateSvc)
    ? readFileSync(stateSvc, "utf-8")
    : "";
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
  if (!existsSync(axisSvc) || !existsSync(programSvc)) {
    assert.match(axisText, /ModulesAxisService/);
    assert.match(programText, /ModulesProgramService/);
    return;
  }

  // ``ModulesAxisService`` exposes only ``/home`` (homing is
  // the one axis-motion action kept on the axis module; the
  // state / mode / MDI endpoints moved to the state module).
  for (const url of ["/api/v1/modules/axis/home"]) {
    assert.match(
      axisText,
      new RegExp(url.replace(/\//g, "\\/")),
      `ModulesAxisService must use ${url}`,
    );
  }
  // ``ModulesMachineStateService`` carries the state / mode / MDI
  // endpoints that used to live alongside ``/home``. The URL
  // prefix is ``/api/v1/modules/machine_state`` (the manifest
  // id of the state module, with the underscore).
  if (stateText) {
    for (const url of [
      "/api/v1/modules/machine_state/state",
      "/api/v1/modules/machine_state/mode",
      "/api/v1/modules/machine_state/mdi",
    ]) {
      assert.match(
        stateText,
        new RegExp(url.replace(/\//g, "\\/")),
        `ModulesMachineStateService must use ${url}`,
      );
    }
  }
  // The legacy ``/api/v1/machine/...`` URLs must no longer
  // appear anywhere in the machine-related generated services.
  for (const url of [
    "/api/v1/machine/state",
    "/api/v1/machine/mode",
    "/api/v1/machine/home",
    "/api/v1/machine/jog",
  ]) {
    const re = new RegExp(url.replace(/\//g, "\\/"));
    assert.doesNotMatch(axisText, re, `ModulesAxisService must not use legacy ${url}`);
    if (stateText) {
      assert.doesNotMatch(stateText, re, `ModulesMachineStateService must not use legacy ${url}`);
    }
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
