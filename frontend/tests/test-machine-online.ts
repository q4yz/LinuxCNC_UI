// Structural guard for the global machine-online gating.
//
// The split deployment runs the system service (:8001, always up)
// and the machine service (:8000, sometimes down). The UI gates all
// machine-level traffic on the ``useMachineOnline`` heartbeat:
//
//   * ``isMachineOnline === null``  → LOADING (skeleton, nothing
//     mounted — never treated as online, so no "reverse flash" of
//     502 spam on an actually-offline boot).
//   * ``false`` → offline card with a Start button (spawns via the
//     always-up system service, 1 Hz fast poll while waking).
//   * ``true``  → machine UI renders; App.vue starts the WS + 1 Hz
//     poll after a 750 ms settle debounce.
//
// The old pending-snapshot watchdog / "connection stuck" modal is
// gone by design — these tests pin both the new surface and the
// removal so a regression trips here rather than in the field.
//
// Run with: ``node --test frontend/tests/test-machine-online.ts``

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
// Composable                                                             //
// ------------------------------------------------------------------ //

test("useMachineOnline composable exists with the three-state contract", () => {
  const path = resolve(src, "composables/useMachineOnline.ts");
  assert.ok(existsSync(path), "composables/useMachineOnline.ts must exist");
  const text = readFileSync(path, "utf-8");

  // ``null`` is the loading state — never a truthy online default.
  assert.match(
    text,
    /ref<boolean \| null>\(null\)/,
    "isMachineOnline must start as null (loading), not optimistic-online",
  );
  // Singleton: the refs live at module scope so every consumer
  // shares one heartbeat.
  assert.ok(
    text.indexOf("const isMachineOnline") < text.indexOf("export function useMachineOnline"),
    "global state must be created OUTSIDE the composable function (singleton)",
  );

  for (const member of [
    "isMachineOnline",
    "isChecking",
    "isStarting",
    "checkMachineOnline",
    "startHeartbeat",
    "stopHeartbeat",
    "wakeMachine",
  ]) {
    assert.match(text, new RegExp(`\\b${member}\\b`), `composable must expose ${member}`);
  }
});

test("probe uses the health route with a short hard timeout", () => {
  const text = read("composables/useMachineOnline.ts");
  assert.match(text, /\/api\/v1\/health/, "probe must hit /api/v1/health on the machine backend");
  assert.match(
    text,
    /AbortSignal\.timeout\(PROBE_TIMEOUT_MS\)/,
    "probe must carry AbortSignal.timeout so a hang cannot stall the heartbeat",
  );
  assert.match(text, /PROBE_TIMEOUT_MS\s*=\s*2_000/, "probe timeout must be 2 s");
  assert.match(text, /cache:\s*"no-store"/, "probe must bypass cache");
});

test("heartbeat cadence: 3 s normal, 1 Hz while waking, 30 s give-up", () => {
  const text = read("composables/useMachineOnline.ts");
  assert.match(text, /NORMAL_INTERVAL_MS\s*=\s*3_000/, "normal cadence must be 3 s");
  assert.match(text, /WAKE_INTERVAL_MS\s*=\s*1_000/, "wake cadence must be 1 s");
  assert.match(text, /WAKE_GIVE_UP_MS\s*=\s*30_000/, "wake give-up guard must be 30 s");
  assert.match(
    text,
    /REQUIRED_FAILURES\s*=\s*2/,
    "online→offline needs 2 consecutive failures (flap hysteresis)",
  );
});

test("wakeMachine spawns via the always-up system service and tolerates 409", () => {
  const text = read("composables/useMachineOnline.ts");
  assert.match(
    text,
    /SystemMachineLifecycleService\.startMachineSession\(\)/,
    "wake must call the :8001 system service, never the dead machine backend",
  );
  assert.match(text, /status\s*===\s*409/, "409 (already running) must keep polling, not error");
  assert.match(
    text,
    /isStarting\.value\s*=\s*false/,
    "failed wake must release the Start button",
  );
});

// ------------------------------------------------------------------ //
// MachineGate                                                            //
// ------------------------------------------------------------------ //

test("MachineGate renders loading / offline / online branches", () => {
  const path = resolve(src, "components/machine/MachineGate.vue");
  assert.ok(existsSync(path), "MachineGate.vue must exist");
  const text = readFileSync(path, "utf-8");

  // Branch 1: null → loading skeleton (NOT the machine UI).
  const loadingIdx = text.indexOf('v-if="isMachineOnline === null"');
  const offlineIdx = text.indexOf('v-else-if="isMachineOnline === false"');
  assert.ok(loadingIdx !== -1, "null must render the loading branch");
  assert.ok(offlineIdx > loadingIdx, "false must render the offline branch after loading");
  assert.match(text, /data-testid="machine-gate-loading"/, "loading branch test id");
  assert.match(text, /data-testid="machine-gate-offline"/, "offline branch test id");

  // Start button: spinner + disabled while starting, wired to wake.
  assert.match(text, /data-testid="machine-gate-start"/, "start button test id");
  assert.match(text, /:loading="isStarting"/, "start button must show in-flight state");
  assert.match(text, /wakeMachine\(\)/, "start button must call wakeMachine()");

  // Branch 3: online → slot.
  assert.match(text, /<slot\s+v-else\s*\/?>/, "online branch must render the slot");
});

// ------------------------------------------------------------------ //
// App.vue wiring                                                         //
// ------------------------------------------------------------------ //

test("App.vue runs the heartbeat and gates machine traffic on it", () => {
  const text = read("App.vue");

  assert.match(text, /useMachineOnline\(\)/, "shell must consume the composable");
  assert.match(text, /startHeartbeat\(\)/, "shell must start the heartbeat");
  assert.match(text, /watch\(\s*isMachineOnline/, "shell must watch the online state");

  // Offline → immediate teardown (never debounced).
  assert.match(text, /stopMachineTraffic\(\)/, "offline must stop machine traffic");
  assert.match(text, /baseThread\.stop\(\)/, "offline must stop the 1 Hz poll");
  assert.match(
    text,
    /servoThreadService\.disconnect\(\)/,
    "offline must close the telemetry WebSocket",
  );

  // Online → debounced connect (backend settle window).
  assert.match(text, /CONNECT_SETTLE_MS\s*=\s*750/, "connect debounce must be 750 ms");
  assert.match(
    text,
    /setTimeout\(/,
    "going online must connect through a settle timeout",
  );
  assert.match(text, /servoThreadService\.connect\(\)/, "online must (re)open the WebSocket");
  assert.match(text, /baseThread\.start\(\)/, "online must (re)start the 1 Hz poll");
});

// ------------------------------------------------------------------ //
// Old idea removed                                                       //
// ------------------------------------------------------------------ //

test("pending-snapshot watchdog and dialog are fully removed", () => {
  assert.ok(
    !existsSync(resolve(src, "components/PendingSnapshotDialog.vue")),
    "PendingSnapshotDialog.vue must be deleted",
  );

  const baseThread = read("stores/baseThread.ts");
  for (const symbol of [
    "PENDING_TIMEOUT_MS",
    "pendingSince",
    "snapshotStaleSince",
    "secondsSinceLastSnapshot",
    "evaluatePending",
    "armWatchdog",
    "rearmPendingPrompt",
    "dismissPendingPrompt",
  ]) {
    assert.ok(
      !new RegExp(`\\b${symbol}\\b`).test(baseThread),
      `baseThread.ts must no longer reference ${symbol}`,
    );
  }

  const header = read("components/EStopHeader.vue");
  assert.ok(
    !/shot-stuck-badge|Stuck \{\{/.test(header),
    "EStopHeader must no longer render the Stuck badge",
  );
  assert.ok(
    !/useBaseThreadStore/.test(header),
    "EStopHeader must no longer read the baseThread store",
  );

  const app = read("App.vue");
  assert.ok(!/PendingSnapshotDialog/.test(app), "App.vue must not mount the dialog");
});

test("facade manual disconnect does not arm the reconnect loop", () => {
  const text = read("facades/servoThreadFacade.ts");
  assert.match(text, /manualClose/, "facade must track deliberate closes");
  assert.match(
    text,
    /if\s*\(this\.manualClose\)\s*return;/,
    "onclose must skip scheduleReconnect on a manual close",
  );
  // The WS liveness stamp + heartbeat handling stay (backend sends
  // ~1 Hz heartbeat frames; they must not warn-spam the console).
  assert.match(text, /noteWsMessage\(\)/, "facade must keep the liveness stamp");
  assert.match(text, /case 'heartbeat':/, "facade must keep the heartbeat case");
});

// ------------------------------------------------------------------ //
// Views gate machine-level widgets                                       //
// ------------------------------------------------------------------ //

test("machine-level widgets are wrapped in MachineGate", () => {
  const expectations = [
    ["views/DashboardView.vue", ["CameraViewer", "DroPanel", "JogControls", "ToolPanel", "TemperaturePanel", "PowerOn", "ActivePrintWidget"]],
    ["views/RunningView.vue", ["AxisSpeedControl", "ToolPanel"]],
    ["views/DebugView.vue", ["DebugPanel"]],
    ["views/FilesView.vue", ["ActivePrintWidget"]],
    ["views/SettingsView.vue", ["CameraSettings", "MachineSettingsPanel", "TemperatureSettingsPanel"]],
  ];

  for (const [rel, widgets] of expectations) {
    const text = read(rel);
    assert.match(text, /MachineGate/, `${rel} must use MachineGate`);
    for (const widget of widgets) {
      assert.match(
        text,
        new RegExp(`<MachineGate[^>]*>\\s*<${widget}[\\s/>]`),
        `${rel}: <${widget}/> must be a direct child of <MachineGate>`,
      );
    }
  }

  // Console stays ungated on the dashboard (system rows + offline
  // explanation live there).
  const dash = read("views/DashboardView.vue");
  assert.match(dash, /<ConsolePanel\s*\/?>/, "ConsolePanel must stay ungated");
});

// ------------------------------------------------------------------ //
// Shared 3D toolpath viewer (single instance, not one per view)          //
// ------------------------------------------------------------------ //
//
// DashboardView and JoggingView used to each mount their own
// NgcCoordinateSystemViewer + MachineGate, so switching between the
// two views tore down one WebGL context and built a new one on every
// click. A single instance now lives in App.vue and is handed
// between the two views via Teleport, gated by one MachineGate.

test("NgcCoordinateSystemViewer is a single shared instance owned by App.vue", () => {
  const app = read("App.vue");
  assert.match(
    app,
    /<MachineGate[^>]*>\s*<NgcCoordinateSystemViewer[^>]*:active="isToolpathViewActive"[^>]*\/>\s*<\/MachineGate>/,
    "App.vue must own the one MachineGate + NgcCoordinateSystemViewer pair",
  );
  assert.match(app, /<Teleport\s+:to="toolpathTeleportTarget"/, "the viewer must be teleported to the active view's slot");
  assert.match(
    app,
    /route\.name === ['"]dashboard['"][\s\S]{0,80}toolpathTeleportTarget\.value = ['"]#toolpath-slot-dashboard['"]/,
    "dashboard route must target the dashboard slot",
  );
  assert.match(
    app,
    /route\.name === ['"]jogging['"][\s\S]{0,80}toolpathTeleportTarget\.value = ['"]#toolpath-slot-jogging['"]/,
    "jogging route must target the jogging slot",
  );
  assert.match(
    app,
    /flush:\s*['"]post['"]/,
    "the teleport target must switch only after <router-view> has patched, so the destination slot already exists",
  );

  // The "parked" fallback target must live in index.html, OUTSIDE
  // the Vue-mounted tree — not in App.vue's own template. Vue mounts
  // an app's whole subtree in one pass, so a target declared inside
  // the same component that contains the Teleport does not exist in
  // the live document yet when the Teleport tries to resolve it on
  // initial mount (this is exactly the "emitsOptions of null" crash
  // this test guards against — Vue warns "Failed to locate Teleport
  // target" and the ensuing render throws).
  assert.doesNotMatch(
    app,
    /id="toolpath-parking"/,
    "the #toolpath-parking div must not be declared inside App.vue — Vue cannot resolve a Teleport target rendered by the same mount pass",
  );
  const indexHtml = readRepo("frontend/index.html");
  assert.match(
    indexHtml,
    /<div id="app">[\s\S]*<div id="toolpath-parking"/,
    "index.html must declare #toolpath-parking as a sibling of #app, outside the Vue-mounted tree",
  );

  // Neither view should own the widget directly any more.
  const dash = read("views/DashboardView.vue");
  const jog = read("views/JoggingView.vue");
  assert.doesNotMatch(dash, /NgcCoordinateSystemViewer/, "DashboardView must not import/mount its own viewer");
  assert.doesNotMatch(jog, /NgcCoordinateSystemViewer/, "JoggingView must not import/mount its own viewer");
  assert.doesNotMatch(jog, /MachineGate/, "JoggingView no longer needs its own MachineGate — the shared instance carries one");

  // Each view exposes the plain slot div the shared instance is
  // teleported into.
  assert.match(dash, /id="toolpath-slot-dashboard"/, "DashboardView must expose the dashboard teleport slot");
  assert.match(jog, /id="toolpath-slot-jogging"/, "JoggingView must expose the jogging teleport slot");

  // DashboardView's slot div is wrapped in a BaseCard (for the
  // "Toolpath" title bar). BaseCard now stagger-defers its default
  // slot by up to 15ms (see test-basecard-stagger.ts) — if this card
  // opted into that, the slot div wouldn't exist yet at the moment
  // App.vue's post-flush watcher tries to Teleport into it right
  // after a route change, throwing "Failed to locate Teleport
  // target" (this is a real regression that was caught live in the
  // browser, not a hypothetical). This card has nothing heavy to
  // defer anyway — the actual viewer lives elsewhere — so it must
  // opt out.
  assert.match(
    dash,
    /<BaseCard title="Toolpath" :stagger="false">[\s\S]{0,500}id="toolpath-slot-dashboard"/,
    "the Toolpath card's BaseCard must opt out of staggering so the teleport slot div exists synchronously on mount",
  );
});

test("the shared viewer pauses its render loop while parked off-route", () => {
  const viewer = read("components/NgcCoordinateSystemViewer.vue");
  assert.match(viewer, /active\?:\s*boolean/, "viewer must accept an active prop");
  assert.match(viewer, /if \(!props\.active\)/, "the RAF loop must bail out while inactive");
  assert.match(
    viewer,
    /watch\(\(\)\s*=>\s*props\.active/,
    "an active watcher must resume the RAF loop when teleported back on screen",
  );
});

// ------------------------------------------------------------------ //
// keep-alive across the three heaviest views                            //
// ------------------------------------------------------------------ //

test("Dashboard/Jogging/Running stay mounted across navigation via keep-alive", () => {
  const app = read("App.vue");
  assert.match(
    app,
    /<keep-alive\s+:include="\['DashboardView',\s*'JoggingView',\s*'RunningView'\]"/,
    "App.vue must keep-alive the three heaviest views by name",
  );
  assert.match(app, /<router-view v-slot="\{\s*Component\s*\}">/, "router-view must expose Component to drive keep-alive");

  for (const [rel, name] of [
    ["views/DashboardView.vue", "DashboardView"],
    ["views/JoggingView.vue", "JoggingView"],
    ["views/RunningView.vue", "RunningView"],
  ]) {
    const text = read(rel);
    assert.match(
      text,
      new RegExp(`defineOptions\\(\\{\\s*name:\\s*['"]${name}['"]\\s*\\}\\)`),
      `${rel} must declare an explicit name matching keep-alive's include list`,
    );
  }
});

// ------------------------------------------------------------------ //
// Backend health probe                                                   //
// ------------------------------------------------------------------ //

test("machine backend exposes /api/v1/health under the proxy prefix", () => {
  const text = readRepo("backend/machine/main.py");
  assert.match(
    text,
    /@app\.get\("\/api\/v1\/health"\)/,
    "route must be declared under /api so the dev/nginx proxy reaches it",
  );
});
