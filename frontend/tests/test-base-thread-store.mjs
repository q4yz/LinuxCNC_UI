// Static-structure tests for the base-thread snapshot store.
//
// Run with: node --test frontend/tests/test-base-thread-store.mjs
//
// The base-thread store is the dashboard's "slow channel" — one
// 1 Hz REST round-trip that bundles every slow stream (program
// progress, temperature sensors, tool list) into one payload so
// the browser issues a single HTTP request per second regardless
// of how many panels are mounted.
//
// The suite validates the contract the consumer modules rely on:
//
//   * The store is a Pinia store via ``defineStore('baseThread', …)``.
//   * State exposes individual refs for every snapshot stream:
//     ``progress``, ``sensors``, ``tools``.
//   * A single ``setInterval`` in ``start`` drives the 1 Hz poll.
//   * A matching ``clearInterval`` in ``stop`` releases the handle.
//   * ``start`` is idempotent (re-entry while running is a no-op).
//   * The progress fraction getter collapses on zero / missing
//     totals and clamps at 100, mirroring the facade's contract.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");

const storePath = resolve(
  repoRoot,
  "frontend/src/stores/baseThread.js",
);

function readStore() {
  return readFileSync(storePath, "utf-8");
}

test("baseThread.js exists and is non-empty", () => {
  assert.ok(
    readFileSync(storePath, "utf-8").length > 0,
    "expected frontend/src/stores/baseThread.js to exist",
  );
});

test("store is registered as a Pinia store via defineStore", () => {
  const text = readStore();
  assert.match(
    text,
    /export\s+const\s+useBaseThreadStore\s*=\s*defineStore\(\s*['"]baseThread['"]/,
  );
  assert.match(text, /state:\s*\(\s*\)\s*=>\s*\(/);
  assert.match(text, /getters:\s*\{/);
  assert.match(text, /actions:\s*\{/);
});

test("store exposes individual refs per snapshot stream", () => {
  // The store must expose ``progress``, ``sensors``, and ``tools``
  // as separate reactive refs so consumers can destructure them
  // via ``storeToRefs`` without losing reactivity. Adding a new
  // stream means adding one new ref + one watcher on the consumer
  // side — no schema migration required.
  const text = readStore();
  assert.match(text, /\bprogress:\s*\{/);
  assert.match(text, /\bsensors:\s*\{/);
  assert.match(text, /\btools:\s*\[\s*\]/);
});

test("start schedules a single setInterval; stop clears it", () => {
  // The store owns exactly one polling interval. The dashboard's
  // single round-trip-per-second contract is the whole point of
  // the snapshot endpoint — adding a second ``setInterval``
  // would silently regress that.
  const text = readStore();
  assert.match(text, /setInterval\s*\(/);
  assert.match(text, /clearInterval\s*\(/);
  // Only one setInterval / clearInterval pair — start fires once,
  // stop fires once.
  const setIntervalCount = (text.match(/setInterval\s*\(/g) || []).length;
  assert.equal(setIntervalCount, 1, "store must own exactly one setInterval");
  const clearIntervalCount = (text.match(/clearInterval\s*\(/g) || []).length;
  assert.equal(
    clearIntervalCount,
    1,
    "store must own exactly one clearInterval",
  );
});

test("start is idempotent — re-entry while running is a no-op", () => {
  // Hot-reloads / double-mounts must not stack intervals. The
  // ``_pollHandle`` sentinel is the canonical pattern. The check
  // must be a truthy one — ``_pollHandle`` is a non-state property
  // on the Pinia store instance, so it is ``undefined`` on the
  // first call. A strict-null check (``!== null``) would evaluate
  // ``undefined !== null`` to ``true`` and silently disable the
  // 1 Hz poll.
  const text = readStore();
  assert.match(
    text,
    /if\s*\(\s*this\._pollHandle\s*\)\s*return/,
    "start() must guard with a truthy check, not a strict-null check (catches undefined on the first call)",
  );
  // Explicitly forbid the broken pattern so the regression cannot
  // be reintroduced without flagging the test.
  assert.doesNotMatch(
    text,
    /if\s*\(\s*this\._pollHandle\s*!==\s*null\s*\)\s*return/,
    "start() must not use a strict-null check — it returns early on the first call because _pollHandle is undefined",
  );
  assert.match(text, /stop\s*\(\s*\)\s*\{[\s\S]*?this\._pollHandle\s*=\s*null/);
});

test("progressFraction getter collapses on zero / missing totals and clamps at 100", () => {
  // Mirrors the facade's ``printProgress`` contract: missing /
  // zero / negative totals collapse to 0, the bar never exceeds
  // 100. Lives on the base-thread store so consumers can read
  // it via ``storeToRefs`` without re-implementing the math.
  const text = readStore();
  assert.match(text, /progressFraction\s*\(\s*state\s*\)\s*\{/);
  assert.match(
    text,
    /total\s*<=\s*0/,
    "progressFraction must collapse to 0 when total_lines is 0",
  );
  assert.match(
    text,
    /Math\.min\(\s*100/,
    "progressFraction must clamp at 100%",
  );
});

test("store calls BaseThreadService.getBaseThreadSnapshot on refresh", () => {
  // The single canonical endpoint for every slow stream. The
  // OpenAPI codegen maps the ``getBaseThreadSnapshot`` operation
  // id onto a dedicated ``BaseThreadService`` class; the store
  // must use that name, not a hand-patched fallback on
  // ``SystemService`` (which the regeneration would silently
  // strip).
  const text = readStore();
  assert.match(
    text,
    /BaseThreadService\.getBaseThreadSnapshot\s*\(/,
  );
  assert.doesNotMatch(
    text,
    /SystemService\.getBaseThreadSnapshot\s*\(/,
  );
});
