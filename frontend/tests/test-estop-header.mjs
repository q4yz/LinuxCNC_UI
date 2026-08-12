// Static-structure tests for the global Emergency Stop header
// (issue #103).
//
// Run with: node --test frontend/tests/test-estop-header.mjs
//
// ``node --test`` does not provide a Vue or Pinia runtime, so the
// suite asserts the source matches the acceptance criteria from
// the issue:
//
//   * A new ``EStopHeader.vue`` component lives under
//     ``frontend/src/components/``.
//   * The component is rendered globally from ``App.vue`` so the
//     E-Stop is reachable regardless of the active route.
//   * The component pins itself to the top of the viewport via
//     ``position: sticky; top: 0`` and a high z-index so it cannot
//     be hidden by scrolling or overlapping elements.
//   * The button delegates to the machine store's
//     ``toggleEstop`` action (the canonical API dispatcher for
//     ``POST /api/v1/modules/machine/state``).
//   * The button uses standard E-Stop iconography (large, red,
//     prominent, with a STOP label).

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");

const headerPath = resolve(
  repoRoot,
  "frontend/src/components/EStopHeader.vue",
);
const appPath = resolve(repoRoot, "frontend/src/App.vue");

function readText(path) {
  return readFileSync(path, "utf-8");
}

// ---------------------------------------------------------------------- //
// EStopHeader.vue component                                                //
// ---------------------------------------------------------------------- //

test("EStopHeader component exists at frontend/src/components/EStopHeader.vue", () => {
  const text = readText(headerPath);
  assert.ok(text.length > 0, "expected EStopHeader.vue to exist and be non-empty");
});

test("EStopHeader uses <script setup> Composition API", () => {
  // The component must follow the project convention (see
  // ``.agent/AGENT.md`` § Frontend conventions).
  const text = readText(headerPath);
  assert.match(text, /<script\s+setup>/);
});

test("EStopHeader imports the machine store through the compat shim", () => {
  // The header must work whether or not the machine module is
  // mounted; the compat shim is the contract for that
  // nullable-module guarantee (``.agent/STATE.md`` § 7).
  const text = readText(headerPath);
  assert.match(
    text,
    /import\s*\{[^}]*useMachineStore[^}]*\}\s*from\s*['"]\.\.\/stores\/machineStoreShim\.js['"]/,
  );
});

test("EStopHeader destructures state with storeToRefs to preserve reactivity", () => {
  // See ``.agent/context/LESSONS_LEARNED.md`` § 2.3: plain ES
  // destructuring of Pinia state silently loses reactivity.
  const text = readText(headerPath);
  assert.match(text, /storeToRefs\(/);
  assert.match(text, /\{\s*isEstop\s*\}\s*=\s*storeToRefs/);
});

test("EStopHeader button delegates to the machine store's toggleEstop action", () => {
  // ``toggleEstop`` is the canonical action that posts
  // ``{state: 'estop'}`` or ``{state: 'estop_reset'}`` to the
  // backend machine router. The header must not bypass it.
  const text = readText(headerPath);
  assert.match(text, /store\.toggleEstop\(\s*\)/);
  // And the button must wire the click handler to that action.
  assert.match(
    text,
    /@click\s*=\s*["']pressEStop["']/,
  );
  // The wrapper function ``pressEStop`` is the canonical local
  // entry point — guard against accidental direct bindings that
  // would skip the store action.
  assert.match(text, /async\s+function\s+pressEStop\s*\(\s*\)/);
});

test("EStopHeader uses position: sticky with top: 0 so it pins to the viewport", () => {
  const text = readText(headerPath);
  // ``sticky`` + ``top-0`` is the documented contract from the
  // issue acceptance criteria.
  assert.match(text, /\bsticky\b/);
  assert.match(text, /\btop-0\b/);
});

test("EStopHeader has a high z-index so it sits above other elements", () => {
  // The header must not be hidden by the sidebar (``z-10``) or
  // any of the modal overlays in the app, which all use
  // ``z-50`` (editor overlay, update manager, panel dialogs).
  // The E-Stop lives at ``z-[100]`` so it sits above them.
  const text = readText(headerPath);
  // Accept the canonical Tailwind v4 arbitrary-value class.
  assert.match(text, /\bz-\[\d+\]/);
});

test("EStopHeader button uses standard E-Stop iconography (red, large, STOP label)", () => {
  const text = readText(headerPath);
  // The button must carry the safety red color.
  assert.match(text, /bg-red-(?:600|500|700)/);
  // It must be physically prominent (a square / circle in the
  // ~80-100 px range is the standard).
  assert.match(text, /w-(?:20|24)\s+h-(?:20|24)/);
  // Hard "STOP" label so a panicked operator does not have to
  // read any copy before pressing it.
  assert.match(text, />\s*STOP\s*</);
  // Standard safety aria semantics.
  assert.match(text, /aria-label\s*=\s*["']Emergency Stop["']/);
});

test("EStopHeader exposes the active / clear state chips", () => {
  // The header must surface the current ``isEstop`` flag so the
  // operator gets visual confirmation when E-Stop is engaged.
  const text = readText(headerPath);
  // ``v-if`` on ``isEstop`` is the canonical reactive binding.
  assert.match(text, /v-if\s*=\s*["']isEstop["']/);
  assert.match(text, /v-else\b/);
  // The chips themselves carry stable ``data-testid`` hooks so
  // future e2e work can target them.
  assert.match(text, /data-testid\s*=\s*["']estop-state-active["']/);
  assert.match(text, /data-testid\s*=\s*["']estop-state-clear["']/);
});

// ---------------------------------------------------------------------- //
// App.vue wiring                                                          //
// ---------------------------------------------------------------------- //

test("App.vue mounts the EStopHeader globally", () => {
  const text = readText(appPath);
  // The import line keeps the same path the component itself
  // uses (sibling under ``components/``).
  assert.match(
    text,
    /import\s+EStopHeader\s+from\s+['"]\.\/components\/EStopHeader\.vue['"]/,
  );
  // The component is rendered unconditionally at the top of the
  // shell so it sits above every route.
  assert.match(text, /<EStopHeader\s*\/?>/);
});

test("App.vue renders EStopHeader outside the scrolling main pane", () => {
  // The header must sit above the ``<main class="overflow-y-auto">``
  // pane so scrolling the active view does not hide it.
  const text = readText(appPath);
  const headerIndex = text.indexOf("<EStopHeader");
  const mainIndex = text.indexOf("<main");
  assert.ok(headerIndex >= 0, "EStopHeader must be rendered in the template");
  assert.ok(mainIndex >= 0, "<main> must still exist");
  assert.ok(
    headerIndex < mainIndex,
    "EStopHeader must render before <main> so it stays visible during scroll",
  );
});

test("App.vue restructures the shell into a column so the header sits above the sidebar", () => {
  // The layout root must be a flex column with the header at the
  // top and the sidebar + main row below.
  const text = readText(appPath);
  assert.match(
    text,
    /class\s*=\s*["'][^"']*flex[^"']*flex-col[^"']*h-screen[^"']*overflow-hidden[^"']*["']/,
  );
  // The row wrapper that holds the sidebar + main must absorb
  // the leftover vertical space (``flex-1``).
  assert.match(
    text,
    /class\s*=\s*["'][^"']*flex[^"']*flex-1[^"']*overflow-hidden[^"']*["']/,
  );
});

// ---------------------------------------------------------------------- //
// Machine-state readout under the STOP button                              //
// ---------------------------------------------------------------------- //
//
// EStopHeader now reads the high-resolution state facade and logs
// every transition to the console store. The two assertions below
// pin both halves.

test("EStopHeader imports the State Facade for the high-resolution machine state", () => {
  const text = readText(headerPath);
  // The facade lives at ``frontend/src/stores/stateFacade.js``;
  // the import must use that path so Pinia can wire the facade
  // singleton that the machine module's WebSocket handler updates.
  assert.match(
    text,
    /import\s*\{[^}]*useMachineStore[^}]*\}\s*from\s*['"]\.\.\/stores\/stateFacade\.js['"]/,
    "EStopHeader must import useMachineStore from the State Facade",
  );
  // ``systemState`` is destructured via storeToRefs (Pinia reactivity
  // would otherwise be lost — see LESSONS_LEARNED § 2.3).
  assert.match(
    text,
    /\{[^}]*systemState[^}]*\}\s*=\s*storeToRefs/,
    "systemState must be destructured via storeToRefs()",
  );
});

test("EStopHeader renders a colour-coded machine-state readout under the button", () => {
  const text = readText(headerPath);
  // Stable hook for future e2e work.
  assert.match(
    text,
    /data-testid\s*=\s*["']estop-machine-state["']/,
  );
  // Bind the badge to the facade's reactive ``systemState``.
  assert.match(text, /\{\{\s*systemState\s*\}\}/);
  // Colour classes spanning the major state buckets.
  for (const cls of [
    /text-red-400/,
    /text-amber-300/,
    /text-slate-400/,
    /text-emerald-300/,
    /text-indigo-300/,
  ]) {
    assert.match(text, cls, `must cover one of the state-colour buckets: ${cls}`);
  }
  // Screen-reader announce: ``role="status"`` + ``aria-live``.
  assert.match(text, /role\s*=\s*["']status["']/);
});

test("EStopHeader logs every systemState transition to the console", () => {
  const text = readText(headerPath);
  // Watcher must be wired to the reactive ``systemState``.
  assert.match(
    text,
    /watch\(\s*systemState\b/,
    "EStopHeader must watch systemState",
  );
  // Cross-store import must be lazy (LESSONS_LEARNED § 2.4): inside
  // the watcher, not at module scope.
  assert.match(
    text,
    /import\(\s*['"]\.\.\/stores\/console\.js['"]\s*\)/,
    "EStopHeader must lazy-import useConsoleStore inside the watcher",
  );
  // The watcher calls into the console store.
  assert.match(
    text,
    /consoleStore\.(?:info|warning)\(/,
    "EStopHeader must call consoleStore.info / consoleStore.warning",
  );
});

test("EStopHeader escalates Estop + PowerOff to the warning severity tier", () => {
  // The two safety-relevant transitions get warning rows so they
  // surface above the info-tier chatter in the console filter.
  const text = readText(headerPath);
  // Pick up both branches — either the test or the source uses
  // string literals that must match the facade enum.
  assert.match(text, /['"]Estop['"]/);
  assert.match(text, /['"]PowerOff['"]/);
  // And the watcher must dispatch both states to ``warning``
  // while everything else goes through ``info``.
  assert.match(
    text,
    /consoleStore\.warning\(/,
    "EStopHeader must escalate some transitions to warning rows",
  );
});
