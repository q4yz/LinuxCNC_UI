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
//   * The store is a Pinia store via ``defineStore('baseThread', …)``
//     — a Composition-API setup store (``() => {...}``), not the
//     Options-API ``{state, getters, actions}`` shape.
//   * State exposes individual refs for every snapshot stream:
//     ``progress``, ``readings``, ``toolList``, plus the legacy
//     ``sensors``/``tools`` refs kept for the migration window.
//   * A single ``setInterval`` in ``armPoll`` (called by ``start``)
//     drives the 1 Hz poll.
//   * A matching ``clearInterval`` in ``stop`` releases the handle.
//   * ``start``/``armPoll`` is idempotent (re-entry while running is
//     a no-op).
//   * The progress fraction getter collapses on zero / missing
//     totals and clamps at 100, mirroring the ``ProgramProgress``
//     entity's own contract.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");

const storePath = resolve(
  repoRoot,
  "frontend/src/stores/baseThread.ts",
);

function readStore() {
  return readFileSync(storePath, "utf-8");
}

test("baseThread.js exists and is non-empty", () => {
  assert.ok(
    readFileSync(storePath, "utf-8").length > 0,
    "expected frontend/src/stores/baseThread.ts to exist",
  );
});

test("store is registered as a Pinia store via defineStore", () => {
  const text = readStore();
  assert.match(
    text,
    /export\s+const\s+useBaseThreadStore\s*=\s*defineStore\(\s*['"]baseThread['"]\s*,\s*\(\s*\)\s*=>\s*\{/,
    "must be a Composition-API setup store: defineStore('baseThread', () => {...})",
  );
  assert.match(text, /return\s*\{[\s\S]*?refresh,[\s\S]*?start,[\s\S]*?stop,?[\s\S]*?\}/);
});

test("store exposes individual refs per snapshot stream", () => {
  // The store must expose ``progress``, ``readings``, ``toolList``,
  // ``sensors``, and ``tools`` as separate reactive refs so
  // consumers can destructure them via ``storeToRefs`` without
  // losing reactivity. Adding a new stream means adding one new
  // ref + one watcher on the consumer side — no schema migration
  // required.
  //
  // After the anti-corruption-layer refactor ``progress`` /
  // ``readings`` / ``toolList`` are entity instances
  // (``ProgramProgress`` / ``ReadingSet`` / ``ToolList``), not
  // plain object literals — the entity owns the math.
  const text = readStore();
  assert.match(text, /\bprogress\s*=\s*shallowRef[<(][\s\S]*?new\s+ProgramProgress\(\)/);
  assert.match(text, /\breadings\s*=\s*shallowRef[<(][\s\S]*?new\s+ReadingSet\(\)/);
  assert.match(text, /\btoolList\s*=\s*shallowRef[<(][\s\S]*?new\s+ToolList\(\[\]\)/);
  // The legacy plain-object/array refs kept for the migration window.
  assert.match(text, /\bsensors\s*=\s*ref[<(][\s\S]*?\(\{\}\)/);
  assert.match(text, /\btools\s*=\s*ref[<(][\s\S]*?\(\[\]\)/);
});

test("start schedules a single setInterval for the snapshot poll; stop clears it", () => {
  // The store owns exactly one snapshot-polling interval. The
  // dashboard's single round-trip-per-second contract is the
  // whole point of the snapshot endpoint — adding a second
  // ``setInterval`` driving ``refresh()`` would silently regress
  // that. A separate watchdog ticker is allowed (it observes
  // timing, it does not call ``refresh()``); this test pins the
  // snapshot poll specifically.
  const text = readStore();
  assert.match(text, /setInterval\s*\(/);
  assert.match(text, /clearInterval\s*\(/);
  // Exactly one ``setInterval`` whose body calls ``refresh()`` —
  // start() schedules the poll once, stop() clears it once.
  const snapPollMatches = text.match(/setInterval\(\s*\(\)\s*=>\s*\{[\s\S]{0,40}refresh\(\)/g) || [];
  assert.equal(
    snapPollMatches.length,
    1,
    "store must own exactly one setInterval driving refresh() (the snapshot poll)",
  );
  // Same anchor on the clear side: only the snapshot poll's
  // handle gets cleared via ``clearInterval(pollHandle)``.
  const snapPollClearMatches = text.match(/clearInterval\(\s*pollHandle\b/g) || [];
  assert.equal(
    snapPollClearMatches.length,
    1,
    "store must own exactly one clearInterval(pollHandle) (the snapshot poll)",
  );
});

test("start is idempotent — re-entry while running is a no-op", () => {
  // Hot-reloads / double-mounts must not stack intervals. ``start()``
  // delegates to ``armPoll()``, which guards on the closure-scoped
  // ``pollHandle`` variable (not a reactive ``ref`` — a plain `let`
  // so Vue never wraps it in a proxy). The check must be truthy,
  // not a strict-null check: on the very first call ``pollHandle``
  // is ``undefined``, and ``undefined !== null`` evaluates to
  // ``true`` — a strict-null guard would silently disable the poll
  // forever after the very first start().
  const text = readStore();
  assert.match(
    text,
    /function\s+armPoll\s*\(\s*\)\s*:\s*void\s*\{[\s\S]*?if\s*\(\s*pollHandle\s*\)\s*return/,
    "armPoll() must guard with a truthy check, not a strict-null check (catches undefined on the first call)",
  );
  // Explicitly forbid the broken pattern so the regression cannot
  // be reintroduced without flagging the test.
  assert.doesNotMatch(
    text,
    /if\s*\(\s*pollHandle\s*!==\s*null\s*\)\s*return/,
    "armPoll() must not use a strict-null check — it would return early on the first call because pollHandle is undefined",
  );
  assert.match(
    text,
    /function\s+stop\s*\(\s*\)\s*:\s*void\s*\{[\s\S]*?pollHandle\s*=\s*null/,
  );
});

test("progressFraction getter collapses on zero / missing totals and clamps at 100", () => {
  // The entity (``ProgramProgress.fraction``) owns the actual
  // 0-collapse / 100-clamp math; the store's computed getter
  // delegates to it and adds a defensive ``Number.isFinite`` guard
  // so a NaN/Infinity can never leak into the progress bar's width.
  const text = readStore();
  assert.match(
    text,
    /const\s+progressFraction\s*=\s*computed\s*\(\s*\(\s*\)\s*=>\s*\{/,
  );
  assert.match(
    text,
    /progress\.value\.fraction/,
    "progressFraction must read from ProgramProgress.fraction",
  );
  assert.match(
    text,
    /Number\.isFinite/,
    "progressFraction must defensively guard against non-finite fractions",
  );
});

// ------------------------------------------------------------------ //
// Static axes: fetched once via the STATIC response tier                //
// ------------------------------------------------------------------ //
//
// `axes` is entirely static (id/jointNumbers/minLimit/maxLimit all
// come from hardware.json at compile time, cached by the backend's
// AxisService singleton). Reassigning it from every 1 Hz `refresh()`
// tick — even though the values never change — handed
// NgcCoordinateSystemViewer's `axisLimits` computed a fresh object
// reference every second, which re-fired its non-deep `watch` and
// rebuilt the whole Three.js grid/outline on every tick. Fetching it
// once via `?mode=static` and never touching it again from the poll
// fixes that at the source, with no consumer-facing change — `axes`
// keeps the exact same name/shape from every component's point of
// view.

test("refresh() no longer assigns axes — it is not this poll's job any more", () => {
  const text = readStore();
  const refreshBody = text.match(/async function refresh\(\)[\s\S]*?\n  \}/)?.[0] ?? "";
  assert.ok(refreshBody, "expected to find the refresh() function body");
  assert.doesNotMatch(
    refreshBody,
    /axes\.value\s*=/,
    "refresh() (the 1 Hz poll) must not reassign axes.value — that would reintroduce a fresh reference every tick",
  );
});

test("fetchStaticAxes fetches the STATIC tier exactly once per session", () => {
  const text = readStore();
  assert.match(text, /async function fetchStaticAxes\s*\(\s*\)\s*:\s*Promise<void>\s*\{/);
  assert.match(
    text,
    /BaseThreadService\.fetchStatic\s*\(/,
    "must go through the facade's dedicated static-tier method, not fetchSnapshot()",
  );
  assert.match(
    text,
    /fetchStaticAxes[\s\S]*?axes\.value\s*=\s*snapshot\.axes/,
    "the static fetch's result must be the one place that assigns axes.value",
  );
  // Idempotent: a loaded flag plus a shared in-flight promise (the
  // same pattern stores/machine.ts uses for refreshSettings()) so
  // concurrent/repeat callers never fire a second request.
  assert.match(text, /if\s*\(\s*staticAxesLoaded\s*\)\s*return/);
  assert.match(text, /if\s*\(\s*staticAxesLoadPromise\s*\)\s*return\s+staticAxesLoadPromise/);
  assert.match(text, /staticAxesLoaded\s*=\s*true/);
});

test("armPoll fires the static axes fetch once, outside the recurring interval", () => {
  const text = readStore();
  const armPollBody = text.match(/function armPoll\(\)[\s\S]*?\n  \}/)?.[0] ?? "";
  assert.ok(armPollBody, "expected to find the armPoll() function body");
  assert.match(
    armPollBody,
    /void fetchStaticAxes\(\)/,
    "armPoll must kick off the one-time static fetch alongside the initial refresh()",
  );
  // Must be called once at the top of armPoll, not from inside the
  // setInterval callback (which would defeat the whole point).
  const insideInterval = armPollBody.match(/setInterval\(\s*\(\)\s*=>\s*\{[\s\S]*?\}/)?.[0] ?? "";
  assert.doesNotMatch(
    insideInterval,
    /fetchStaticAxes/,
    "fetchStaticAxes must not be called from inside the recurring setInterval",
  );
});

test("BaseThreadService.fetchStatic requests the static tier via the generated client", () => {
  const facadeText = readFileSync(
    resolve(repoRoot, "frontend/src/facades/baseThreadFacade.ts"),
    "utf-8",
  );
  assert.match(
    facadeText,
    /static async fetchStatic\s*\(\s*\)\s*:\s*Promise<Snapshot>\s*\{/,
  );
  assert.match(
    facadeText,
    /ApiBaseThreadService\.getBaseThreadSnapshot\(\s*["']static["']\s*\)/,
    "fetchStatic must request mode=static from the generated client",
  );
});

test("store calls BaseThreadService.fetchSnapshot on refresh, which wraps the generated getBaseThreadSnapshot op", () => {
  // The store goes through the domain facade
  // (``facades/baseThreadFacade.ts``), not the generated client
  // directly. The facade's ``BaseThreadService.fetchSnapshot()`` is
  // the one place that calls the OpenAPI-generated
  // ``getBaseThreadSnapshot`` operation — pin both ends of that
  // chain so a hand-patched fallback (e.g. onto ``SystemService``,
  // which a regeneration would silently strip) can't sneak in at
  // either layer.
  const text = readStore();
  assert.match(text, /BaseThreadService\.fetchSnapshot\s*\(/);

  const facadeText = readFileSync(
    resolve(repoRoot, "frontend/src/facades/baseThreadFacade.ts"),
    "utf-8",
  );
  assert.match(facadeText, /ApiBaseThreadService\.getBaseThreadSnapshot\s*\(/);
  assert.doesNotMatch(facadeText, /SystemService\.getBaseThreadSnapshot\s*\(/);
});
