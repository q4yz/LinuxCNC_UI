// Structural guard for the pending-snapshot watchdog.
//
// The base-thread store owns a 1 Hz watchdog that surfaces a modal
// when the dashboard has not received a snapshot in 6 s. The widget
// wires the dialog and a small "Stuck for Ns" badge off the same
// store state. These tests pin the shape so a future rename trips
// here rather than at runtime.
//
// Run with: ``node --test frontend/tests/test-pending-snapshot.ts``

import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");
const src = resolve(repoRoot, "frontend/src");

const read = (rel) => readFileSync(resolve(src, rel), "utf-8");

test("baseThread exposes the pending-snapshot watchdog state + actions", () => {
  const text = read("stores/baseThread.ts");

  assert.match(text, /PENDING_TIMEOUT_MS\s*=\s*6_000/, "watchdog threshold must be 6 s");
  assert.match(text, /PENDING_DISMISS_COOLDOWN_MS\s*=\s*60_000/, "dismiss cooldown must be 60 s");

  for (const field of [
    "pendingSince",
    "secondsSinceLastSnapshot",
    "isPending",
  ]) {
    assert.match(text, new RegExp(`\\b${field}\\b`), `store must expose ${field}`);
  }

  for (const action of [
    "dismissPendingPrompt",
    "rearmPendingPrompt",
    "armPoll",
    "armWatchdog",
  ]) {
    assert.match(
      text,
      new RegExp(`function\\s+${action}\\b`),
      `store must define ${action}()`,
    );
  }

  // start() must arm poll and watchdog independently — the old
  // single ``if (pollHandle) return`` guard could leave the watchdog
  // silent when the poll was already live.
  assert.match(
    text,
    /function start\(\): void \{\s*armPoll\(\);\s*armWatchdog\(\);\s*\}/,
    "start() must arm both timers independently",
  );
  // Field marker so the operator can verify the new bundle is live.
  assert.match(
    text,
    /watchdog armed/,
    "armWatchdog must log a one-time console marker",
  );
});

test("refresh() success clears the pending state", () => {
  const text = read("stores/baseThread.ts");
  // The success branch of refresh() must stamp lastSuccessAt and
  // reset the sticky pending timer; otherwise the dialog would
  // never close on its own after a recovery.
  const successRegion = text.match(
    /\/\/ Entity Surface[\s\S]*?pendingSince\.value\s*=\s*null;/
  );
  assert.ok(successRegion, "refresh() must clear pendingSince on success");
  assert.match(successRegion[0], /lastSuccessAt\.value\s*=\s*Date\.now\(\)/);
});

test("App.vue mounts the PendingSnapshotDialog globally", () => {
  const app = read("App.vue");
  assert.match(
    app,
    /import PendingSnapshotDialog from ["']\.\/components\/PendingSnapshotDialog\.vue["']/,
    "App.vue must import PendingSnapshotDialog",
  );
  assert.match(
    app,
    /<PendingSnapshotDialog\s*\/?>/,
    "App.vue must mount the dialog component",
  );
});

test("PendingSnapshotDialog reads pendingSince and offers Refresh/Reload/Dismiss", () => {
  const path = resolve(src, "components/PendingSnapshotDialog.vue");
  assert.ok(existsSync(path), "PendingSnapshotDialog.vue must exist");
  const text = readFileSync(path, "utf-8");

  assert.match(text, /pendingSince/, "dialog must read pendingSince from the store");
  assert.match(text, /secondsSinceLastSnapshot/, "dialog must show secondsSinceLastSnapshot");
  assert.match(text, /Refresh now/, "dialog must offer a Refresh now button");
  assert.match(text, /Reload page/, "dialog must offer a Reload page button");
  assert.match(text, /Dismiss/, "dialog must offer a Dismiss button");
  assert.match(text, /window\.location\.reload\(\)/, "Reload page must hard-reload");
  assert.match(
    text,
    /store\.refresh\(\)/,
    "Refresh now must call store.refresh()",
  );
  assert.match(
    text,
    /rearmPendingPrompt\(\)/,
    "Refresh now must re-arm via rearmPendingPrompt()",
  );
  assert.match(
    text,
    /dismissPendingPrompt\(\)/,
    "Dismiss must call store.dismissPendingPrompt()",
  );
});

test("EStopHeader surfaces a Stuck-for-Ns badge while pending", () => {
  const text = read("components/EStopHeader.vue");
  assert.match(text, /pendingSince/, "header must bind to pendingSince");
  assert.match(text, /secondsSinceLastSnapshot/, "header must show secondsSinceLastSnapshot");
  assert.match(
    text,
    /Stuck\s*\{\{[^}]*secondsSinceLastSnapshot/,
    "header must render a 'Stuck Ns' badge",
  );
  assert.match(
    text,
    /v-if=["']pendingSince !== null["']/,
    "header badge must be gated on a non-null pendingSince",
  );
  assert.match(
    text,
    /shot-stuck-badge/,
    "header badge must carry a stable test id",
  );
});
