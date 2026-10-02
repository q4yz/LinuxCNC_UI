// Behavioural tests for ``src/ui/useBackendSync.ts`` — the shared
// optimistic-update state machine behind BaseCheckbox / BaseRange /
// BaseSelect.
//
// Contract pinned here:
//   * no backend value -> ``null`` (never a default), ``isSynced`` false
//   * commit -> optimistic value shown + emitted, pending until echoed
//   * echo -> confirmed; no echo within the timeout -> revert + error log
//   * no listener -> local-only change + warning

import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { resolve, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = (p: string) => pathToFileURL(resolve(here, "../src", p)).href;

// ``useBackendSync`` arms ``window.setTimeout``; node has no window.
(globalThis as any).window ??= globalThis;

const { createPinia, setActivePinia } = await import("pinia");
const { ref, nextTick } = await import("vue");
const { useBackendSync } = await import(src("ui/useBackendSync.ts"));
const { useConsoleStore } = await import(src("stores/console.ts"));

beforeEach(() => setActivePinia(createPinia()));

function setup(opts: { listener?: boolean; timeoutMs?: number; initial?: number | null } = {}) {
  const backend = ref<number | null>(opts.initial ?? null);
  const emitted: number[] = [];
  const sync = useBackendSync<number>({
    label: () => "Test Control",
    source: () => backend.value,
    hasListener: () => opts.listener ?? true,
    emit: (v: number) => emitted.push(v),
    timeoutMs: () => opts.timeoutMs ?? 30,
  });
  const logs = () => useConsoleStore().messages.map((m: any) => `${m.type}:${m.text}`);
  return { backend, emitted, sync, logs };
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

test("no backend value means null and unsynced — never a default", () => {
  const { sync, logs } = setup();
  assert.equal(sync.displayValue.value, null);
  assert.equal(sync.isSynced.value, false);
  assert.ok(logs().some((l: string) => l.includes("Test Control: waiting for backend value")));
});

test("a commit shows the requested value until the backend echoes it", async () => {
  const { backend, emitted, sync, logs } = setup({ initial: 1 });
  sync.commit(5);
  assert.deepEqual(emitted, [5]);
  assert.equal(sync.isPending.value, true);
  assert.equal(sync.displayValue.value, 5);

  backend.value = 5;
  await nextTick();
  assert.equal(sync.isPending.value, false);
  assert.equal(sync.displayValue.value, 5);
  assert.ok(logs().some((l: string) => l.includes("Test Control: confirmed → 5")));
});

test("no echo within the timeout reverts to the backend value and logs an error", async () => {
  const { sync, logs } = setup({ initial: 1, timeoutMs: 20 });
  sync.commit(5);
  await sleep(40);
  assert.equal(sync.isPending.value, false);
  assert.equal(sync.displayValue.value, 1);
  assert.ok(logs().some((l: string) => l.startsWith("error:") && l.includes("did not confirm 5")));
});

test("committing the value the backend already has sends nothing", () => {
  const { emitted, sync } = setup({ initial: 3 });
  sync.commit(3);
  assert.deepEqual(emitted, []);
  assert.equal(sync.isPending.value, false);
});

test("a parent without a listener gets a local-only change and a warning", () => {
  const { emitted, sync, logs } = setup({ listener: false, initial: 1 });
  sync.commit(7);
  assert.deepEqual(emitted, []);
  assert.equal(sync.displayValue.value, 7);
  assert.ok(logs().some((l: string) => l.startsWith("warning:") && l.includes("nothing sent to backend")));
});

test("losing the backend value after a sync is logged", async () => {
  const { backend, logs } = setup({ initial: 2 });
  backend.value = null;
  await nextTick();
  assert.ok(logs().some((l: string) => l.includes("backend value lost (was 2)")));
});
