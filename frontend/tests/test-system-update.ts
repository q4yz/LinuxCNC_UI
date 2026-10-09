// System update tracking (stores/systemUpdate.ts): the overlay follows
// the status scripts/update.sh writes — never a fixed timer, never
// "the service answers again" — and notifies on finish / failure.
//
// The generated ``SystemService`` statics are stubbed; the poll loop is
// driven with node's mock timers.

import { test, beforeEach, afterEach, mock } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");
const url = (p: string) => pathToFileURL(resolve(repoRoot, p)).href;
const read = (p: string) => readFileSync(resolve(repoRoot, "frontend/src", p), "utf-8");

// --- browser shims ------------------------------------------------------ //
let reloads = 0;
const storage = new Map<string, string>();
(globalThis as any).window ??= globalThis;
(globalThis as any).window.location = { reload: () => { reloads++; } };
(globalThis as any).window.localStorage = {
  getItem: (k: string) => storage.get(k) ?? null,
  setItem: (k: string, v: string) => void storage.set(k, v),
};

const { createPinia, setActivePinia } = await import("pinia");
const { SystemService } = await import(url("frontend/generated/api/services/SystemService.ts"));
const { useSystemUpdateStore } = await import(url("frontend/src/stores/systemUpdate.ts"));
const { useConsoleStore } = await import(url("frontend/src/stores/console.ts"));

// --- fake backend ---------------------------------------------------------- //
type Wire = Record<string, unknown> | "down";
let current: Wire = { state: "idle" };
SystemService.getSystemUpdateStatus = async () => {
  if (current === "down") throw new Error("502 Bad Gateway");
  return current;
};
SystemService.triggerSystemUpdate = async () => ({ status: "update initiated", run_id: "run-new" });

const now = () => new Date().toISOString();
const flush = async () => { for (let i = 0; i < 10; i++) await Promise.resolve(); };
async function tick() {
  mock.timers.tick(2000);
  await flush();
}
const messages = () => useConsoleStore().messages.map((m: any) => `${m.type}:${m.text}`);

beforeEach(() => {
  setActivePinia(createPinia());
  mock.timers.enable({ apis: ["setTimeout"] });
  reloads = 0;
  storage.clear();
  current = { state: "idle" };
});
afterEach(() => mock.timers.reset());

test("overlay stays through the outage and an older run's status; done reloads", async () => {
  // An older run's "done" is still in the file when ours starts.
  current = { run_id: "run-old", state: "done", phase: "finished", finished_at: now() };
  const store = useSystemUpdateStore();
  const result = await store.start();
  assert.equal(result.ok, true);
  assert.equal(store.runId, "run-new");
  assert.equal(store.mode, "running");

  await tick(); // old run's "done" must not end ours
  assert.equal(store.mode, "running");
  assert.equal(reloads, 0);

  current = { run_id: "run-new", state: "running", phase: "rebuilding UI", updated_at: now() };
  await tick();
  assert.equal(store.status.phase, "rebuilding UI");

  current = "down"; // system service restarting — keep waiting
  await tick();
  await tick();
  assert.equal(store.mode, "running");
  assert.notEqual(store.unreachableSince, null);
  assert.equal(reloads, 0);

  current = { run_id: "run-new", state: "done", phase: "finished", finished_at: now(), commit_after: "abc1234" };
  await tick();
  assert.equal(reloads, 1, "done reloads into the new build");
});

test("failure keeps the overlay with the reason and notifies once", async () => {
  const store = useSystemUpdateStore();
  await store.start();
  current = {
    run_id: "run-new", state: "failed", phase: "pull", message: "Update failed during 'pull' (exit code 1)",
    finished_at: now(), log_tail: "fatal: unable to access",
  };
  await tick();
  assert.equal(store.mode, "failed");
  assert.equal(store.status.logTail, "fatal: unable to access");
  assert.equal(reloads, 0);
  assert.ok(messages().some((m: string) => m.startsWith("error:") && m.includes("failed during 'pull'")));

  store.dismiss();
  assert.equal(store.mode, "idle");
});

test("after the reload: a finished run is announced once", async () => {
  current = { run_id: "run-new", state: "done", phase: "finished", finished_at: now(), commit_after: "abc1234" };
  await useSystemUpdateStore().resume();
  assert.ok(messages().some((m: string) => m.startsWith("success:") && m.includes("abc1234")));

  setActivePinia(createPinia()); // next app start
  await useSystemUpdateStore().resume();
  assert.ok(!messages().some((m: string) => m.startsWith("success:")), "not announced twice");
});

test("an old finished run is not announced", async () => {
  const old = new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString();
  current = { run_id: "run-old", state: "done", phase: "finished", finished_at: old };
  await useSystemUpdateStore().resume();
  assert.ok(!messages().some((m: string) => m.startsWith("success:")));
});

test("a running update is picked up on app start (reload / other browser)", async () => {
  current = { run_id: "run-x", state: "running", phase: "dependencies", updated_at: now() };
  const store = useSystemUpdateStore();
  await store.resume();
  assert.equal(store.mode, "running");
  assert.equal(store.runId, "run-x");
});

test("an idle, already-open browser picks up an update started elsewhere", async () => {
  const store = useSystemUpdateStore();
  await store.resume(); // app start: nothing running
  assert.equal(store.mode, "idle");

  current = { run_id: "run-elsewhere", state: "running", phase: "pull", updated_at: now() };
  mock.timers.tick(15000);
  await flush();
  assert.equal(store.mode, "running");
  assert.equal(store.runId, "run-elsewhere");
});

test("finish / failure notifications pop up as toasts", () => {
  const text = read("stores/systemUpdate.ts");
  const popups = text.match(/popup: true, title: "System update"|popup: true,\s+title: "System update"/g) ?? [];
  assert.ok(popups.length >= 3, "success, failure and unreachable must all set popup: true");
});

test("UpdateManager no longer reloads on a fixed timer; the overlay lives in App.vue", () => {
  const manager = read("components/UpdateManager.vue");
  assert.doesNotMatch(manager, /setTimeout/);
  assert.doesNotMatch(manager, /window\.location\.reload/);
  assert.match(manager, /updateStore\.start\(\)/);
  const app = read("App.vue");
  assert.match(app, /<UpdateOverlay \/>/);
  assert.match(app, /systemUpdate\.resume\(\)/);
});

test("the update never boots temporary backends on the real ports", () => {
  const rebuild = readFileSync(resolve(repoRoot, "rebuild_ui.sh"), "utf-8");
  assert.doesNotMatch(rebuild, /uvicorn/);
  assert.match(rebuild, /dump_openapi\.py" machine/);
  assert.match(rebuild, /OPENAPI_FILE=/);
  const update = readFileSync(resolve(repoRoot, "scripts/update.sh"), "utf-8");
  // "done" only after the health check, as the very last status write.
  assert.ok(update.indexOf("status done") > update.indexOf("api/v1/system/version"));
  assert.match(update, /trap on_exit EXIT/);
});
