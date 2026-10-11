// useMachineOnline: the offline card says *why* the machine UI is not
// available, from the machine backend's health body plus the always-up
// system service's session state.

import { test, mock } from "node:test";
import assert from "node:assert/strict";
import { resolve, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = (p: string) => pathToFileURL(resolve(here, "../src", p)).href;

(globalThis as any).window ??= globalThis;

type Reply = { status: number; body?: unknown } | "network-error";
let health: Reply = "network-error";
let session: Reply = "network-error";

(globalThis as any).fetch = async (url: string) => {
  const reply = String(url).includes("/api/v1/health") ? health : session;
  if (reply === "network-error") throw new TypeError("fetch failed");
  return {
    ok: reply.status >= 200 && reply.status < 300,
    status: reply.status,
    json: async () => reply.body ?? {},
  };
};

const { createPinia, setActivePinia } = await import("pinia");
setActivePinia(createPinia());
const { useMachineOnline } = await import(src("composables/useMachineOnline.ts"));
const online = useMachineOnline();

const status = (state: string) => ({ status: 200, body: { state, running: state === "running", pids: [] } });

async function probe() {
  await online.checkMachineOnline();
}

test("backend down + session starting -> starting", async () => {
  health = { status: 502 };
  session = status("starting");
  await probe();
  assert.equal(online.isMachineOnline.value, false);
  assert.equal(online.offlineReason.value, "starting");
});

test("backend down + session stopped -> stopped (Start offered)", async () => {
  session = status("stopped");
  await probe();
  assert.equal(online.offlineReason.value, "stopped");
});

test("backend up but LinuxCNC not readable -> connecting, not online", async () => {
  health = { status: 200, body: { status: "ok", linuxcnc_connected: false, shutting_down: false } };
  session = status("running");
  await probe();
  await probe();
  assert.equal(online.isMachineOnline.value, false);
  assert.equal(online.offlineReason.value, "connecting");
});

test("backend shutting down -> stopping", async () => {
  health = { status: 200, body: { status: "ok", linuxcnc_connected: true, shutting_down: true } };
  await probe();
  assert.equal(online.offlineReason.value, "stopping");
});

test("LinuxCNC running, backend unreachable: waiting, then unresponsive after 20 s", async () => {
  mock.timers.enable({ apis: ["Date"], now: 1_000_000 });
  try {
    health = { status: 502 };
    session = status("running");
    await probe();
    assert.equal(online.offlineReason.value, "waiting");

    mock.timers.tick(21_000);
    await probe();
    assert.equal(online.offlineReason.value, "unresponsive");
  } finally {
    mock.timers.reset();
  }
});

test("system service unreachable too -> system-offline", async () => {
  health = "network-error";
  session = "network-error";
  await probe();
  assert.equal(online.offlineReason.value, "system-offline");
});

test("healthy and readable -> online, no reason", async () => {
  health = { status: 200, body: { status: "ok", linuxcnc_connected: true, shutting_down: false } };
  await probe();
  assert.equal(online.isMachineOnline.value, true);
  assert.equal(online.offlineReason.value, null);
});

test("an older backend without the new health fields still counts as online", async () => {
  health = { status: 200, body: { status: "ok", service: "machine" } };
  await probe();
  assert.equal(online.isMachineOnline.value, true);
});

test("LinuxCNC started by another process (foreign INI) -> external, shown offline", async () => {
  health = "network-error";
  session = { status: 200, body: { state: "running", running: true, owner: "external", running_ini: "/home/cnc/sim/axis.ini", pids: [42] } };
  await probe();
  await probe(); // was online: two failed probes flip it (hysteresis)
  assert.equal(online.isMachineOnline.value, false);
  assert.equal(online.offlineReason.value, "external");
  assert.equal(online.runningIni.value, "/home/cnc/sim/axis.ini");
});

test("Start while an external session runs fails with the system service's reason", async () => {
  const { SystemMachineLifecycleService } = await import(
    pathToFileURL(resolve(here, "../generated/api/services/SystemMachineLifecycleService.ts")).href
  );
  const { useConsoleStore } = await import(src("stores/console.ts"));
  const detail = "Cannot start: LinuxCNC is already running from another process (pids [42] with /home/cnc/sim/axis.ini). Terminate that LinuxCNC session first, then start the machine from this UI.";
  SystemMachineLifecycleService.startMachineSession = async () => {
    throw Object.assign(new Error("Conflict"), { status: 409, body: { detail } });
  };

  await online.wakeMachine();

  assert.equal(online.isStarting.value, false, "the Start button is released");
  const messages = useConsoleStore().messages.map((m: any) => `${m.type}:${m.text}`);
  assert.ok(
    messages.some((m: string) => m.startsWith("error:") && m.includes("another process") && m.includes("Terminate")),
    `expected the external-session error, got ${JSON.stringify(messages.slice(-3))}`,
  );
  online.stopHeartbeat();
});
