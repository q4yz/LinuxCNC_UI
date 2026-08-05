// Frontend tests for the new console features (issue #40).
//
// Run with: node --test frontend/tests/test-console-features.mjs
//
// These tests cover the **static structure** of the new console
// features because we cannot drive a Pinia store from bare
// ``node --test`` (no Pinia runtime, no Vue runtime). The
// companion ``vite build`` step in CI validates the dynamic
// / type-level regressions.
//
// The features under test are:
//
//   * ``console.js`` — Pinia store with log-level filtering. The
//     store exposes a ``filteredMessages`` ``computed`` (i.e. a
//     getter) that filters by the active ``filterLevel``.
//   * ``gcodes.js``  — autocomplete dictionary +
//     ``filterAutocompleteCommands`` helper.
//   * ``ConsolePanel.vue`` — autocomplete menu, keyboard navigation,
//     level chip row, level-aware message list.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");

const consoleStorePath = resolve(repoRoot, "frontend/src/stores/console.js");
const gcodesPath = resolve(repoRoot, "frontend/src/config/gcodes.js");
const consolePanelPath = resolve(
  repoRoot,
  "frontend/src/components/ConsolePanel.vue",
);

function readText(path) {
  return readFileSync(path, "utf-8");
}

// ---------------------------------------------------------------------- //
// console store                                                           //
// ---------------------------------------------------------------------- //


test("console store exposes the four canonical log levels", () => {
  const text = readText(consoleStorePath);
  // The store exports ``LOG_LEVELS`` (all / debug / info / warning /
  // error) so the chip row can iterate the same vocabulary the
  // store validates against. Order is the current authoritative
  // sequence; ``debug`` sits between ``all`` and ``info`` so the
  // ``filteredMessages`` index comparison keeps the severity
  // ordering correct.
  assert.match(
    text,
    /export\s+const\s+LOG_LEVELS\s*=\s*\[\s*['"]all['"]\s*,\s*['"]debug['"]\s*,\s*['"]info['"]\s*,\s*['"]warning['"]\s*,\s*['"]error['"]\s*\]/,
  );
});


test("console store exports a type-to-level mapping", () => {
  const text = readText(consoleStorePath);
  // The mapping table drives the ``level`` field on every
  // message. ``info`` / ``success`` / ``command`` collapse to
  // ``info`` so the ``Info`` chip surfaces the historic rows.
  assert.match(text, /typeToLevel/);
  assert.match(text, /TYPE_TO_LEVEL/);
  assert.match(text, /success:\s*['"]info['"]/);
  assert.match(text, /command:\s*['"]info['"]/);
  assert.match(text, /warning:\s*['"]warning['"]/);
  assert.match(text, /error:\s*['"]error['"]/);
});


test("console store attaches a level field to every message", () => {
  const text = readText(consoleStorePath);
  // ``addMessage`` must decorate the row with ``level`` so the
  // getter can filter without re-deriving the value every time.
  assert.match(text, /level\s*=\s*typeToLevel\(type\)/);
  assert.match(text, /level,/);
});


test("console store exposes a filteredMessages getter", () => {
  const text = readText(consoleStorePath);
  // The getter must be a Pinia getter (under ``getters``) so the
  // computed dependency tracking kicks in.
  assert.match(text, /getters\s*:/);
  assert.match(text, /filteredMessages\s*:\s*\(state\)/);
  // The filter must short-circuit on ``all`` and otherwise
  // compare ``msg.level`` against the active ``filterLevel``.
  assert.match(text, /if\s*\(\s*state\.filterLevel\s*===\s*['"]all['"]/);
  assert.match(text, /state\.filterLevel/);
  assert.match(text, /msg\.level/);
});


test("console store guards setFilterLevel against unknown values", () => {
  const text = readText(consoleStorePath);
  assert.match(text, /setFilterLevel\(level\)/);
  // The body must reject unknown levels so the chip row cannot
  // point the store at a value the getter does not understand.
  assert.match(text, /if\s*\(\s*!LOG_LEVELS\.includes\(level\)\s*\)\s*return/);
});


test("console store exposes a debug action that routes through _addMessage", () => {
  const text = readText(consoleStorePath);
  // The current store exposes a ``debug(text)`` action that
  // delegates to the internal ``_addMessage(text, 'debug')``
  // helper. The legacy ``addDebug`` shim was removed in favor
  // of direct level-named actions.
  assert.match(text, /debug\(text\)/);
  assert.match(text, /_addMessage\(text,\s*['"]debug['"]\)/);
});


// ---------------------------------------------------------------------- //
// gcodes autocomplete dictionary                                          //
// ---------------------------------------------------------------------- //


test("gcodes exports an autocomplete dictionary covering G and M codes", () => {
  const text = readText(gcodesPath);
  // The dictionary must be a single exported constant so the
  // console can import it without registering a service.
  assert.match(text, /export\s+const\s+AUTOCOMPLETE_COMMANDS/);
  // Spot-check the canonical motion / motion-modal codes.
  assert.match(text, /['"]G0['"]/);
  assert.match(text, /['"]G1['"]/);
  assert.match(text, /['"]G21['"]/);
  assert.match(text, /['"]G90['"]/);
  // M-codes.
  assert.match(text, /['"]M3['"]/);
  assert.match(text, /['"]M5['"]/);
  assert.match(text, /['"]M30['"]/);
  // System commands.
  assert.match(text, /['"]HOME['"]/);
  assert.match(text, /['"]ESTOP['"]/);
});


test("gcodes entries carry a category and description", () => {
  const text = readText(gcodesPath);
  // Every entry must have the four documented fields so the
  // autocomplete menu can render the description column.
  assert.match(text, /category:\s*['"]gcode['"]/);
  assert.match(text, /category:\s*['"]mcode['"]/);
  assert.match(text, /category:\s*['"]system['"]/);
  assert.match(text, /description:/);
});


test("filterAutocompleteCommands returns empty for empty input", () => {
  // Round-trip the function via a fresh ``data:`` import so the
  // test does not depend on the rest of the source tree (the
  // helper is a pure function).
  const tmp = resolve(here, "../src/config/gcodes.js");
  const url = "file://" + tmp;
  // We use a dynamic import in a Promise so ``node --test`` does
  // not have to be configured for ESM.
  return import(url).then((mod) => {
    assert.deepEqual(mod.filterAutocompleteCommands(""), []);
    assert.deepEqual(mod.filterAutocompleteCommands("   "), []);
    assert.deepEqual(mod.filterAutocompleteCommands(null), []);
  });
});


test("filterAutocompleteCommands is case-insensitive on the label", () => {
  const url = "file://" + resolve(here, "../src/config/gcodes.js");
  return import(url).then((mod) => {
    const matches = mod.filterAutocompleteCommands("g1", 5);
    assert.ok(matches.length > 0, "G1 must match for lowercase 'g1'");
    assert.ok(matches.some((entry) => entry.label === "G1"));
  });
});


test("filterAutocompleteCommands caps the result count", () => {
  const url = "file://" + resolve(here, "../src/config/gcodes.js");
  return import(url).then((mod) => {
    // ``G`` is a prefix for many G-codes; the helper must cap
    // the result to the supplied limit so the menu never
    // overflows the viewport.
    const matches = mod.filterAutocompleteCommands("G", 3);
    assert.equal(matches.length, 3);
  });
});


test("filterAutocompleteCommands matches descriptions", () => {
  const url = "file://" + resolve(here, "../src/config/gcodes.js");
  return import(url).then((mod) => {
    // Searching for the description snippet must surface
    // relevant commands even when the label does not start
    // with the query.
    const matches = mod.filterAutocompleteCommands("dwell", 5);
    assert.ok(matches.length > 0);
    assert.ok(matches.some((entry) => entry.label === "G4"));
  });
});


// ---------------------------------------------------------------------- //
// ConsolePanel.vue                                                        //
// ---------------------------------------------------------------------- //


test("ConsolePanel renders a log-level chip row", () => {
  const text = readText(consolePanelPath);
  // The chip row iterates ``LOG_LEVELS`` so the UI cannot drift
  // out of sync with the store's vocabulary.
  assert.match(text, /v-for="level in LOG_LEVELS"/);
  // Each chip must be a button with the active-state flag bound
  // to ``filterLevel``.
  assert.match(text, /@click="filterLevel = level"/);
  assert.match(text, /filterLevel === level/);
});


test("ConsolePanel iterates over filteredMessages only", () => {
  const text = readText(consolePanelPath);
  // The renderer must use the getter, not the raw messages
  // array, so the level filter actually hides rows.
  assert.match(text, /v-for="msg in consoleStore\.filteredMessages"/);
  // Ensure the raw array is no longer the iteration source.
  assert.doesNotMatch(text, /v-for="msg in consoleStore\.messages"/);
});


test("ConsolePanel wires the autocomplete menu", () => {
  const text = readText(consolePanelPath);
  // The menu is ``v-if``-ed on the computed ``suggestions`` so
  // it auto-hides when the input is empty.
  assert.match(text, /v-if="showSuggestions && suggestions\.length > 0"/);
  // Each row is clickable via ``mousedown.prevent`` so the
  // input does not lose focus before the handler fires.
  assert.match(text, /@mousedown\.prevent="selectSuggestion\(entry\)"/);
});


test("ConsolePanel handles ArrowUp, ArrowDown, Tab, Enter and Escape", () => {
  const text = readText(consolePanelPath);
  // The ``onKeyDown`` handler must intercept the navigation keys
  // while the menu is open. ``preventDefault`` keeps the browser
  // from moving the caret on ArrowUp / ArrowDown.
  assert.match(text, /event\.key === ['"]ArrowDown['"]/);
  assert.match(text, /event\.key === ['"]ArrowUp['"]/);
  assert.match(text, /event\.key === ['"]Tab['"]/);
  assert.match(text, /event\.key === ['"]Enter['"]/);
  assert.match(text, /event\.key === ['"]Escape['"]/);
  assert.match(text, /moveSuggestion\(1\)/);
  assert.match(text, /moveSuggestion\(-1\)/);
});


test("ConsolePanel hides the menu when the input is empty", () => {
  const text = readText(consolePanelPath);
  // ``onInput`` opens the menu only when there is non-whitespace
  // content so the menu never opens on focus alone.
  assert.match(text, /commandInput\.value\.trim\(\)\.length > 0/);
});


test("ConsolePanel cleans up its document listener on unmount", () => {
  const text = readText(consolePanelPath);
  // A document-level ``mousedown`` listener is required to hide
  // the menu when the user clicks outside; the ``onBeforeUnmount``
  // hook must remove it so the panel does not leak the callback
  // across hot reloads.
  assert.match(text, /document\.addEventListener\(\s*['"]mousedown['"]/);
  assert.match(text, /document\.removeEventListener\(\s*['"]mousedown['"]/);
  assert.match(text, /onBeforeUnmount/);
});


test("ConsolePanel renders level-aware Tailwind colors", () => {
  const text = readText(consolePanelPath);
  // Red for Error, Yellow for Warning, Gray for Debug — the
  // exact mapping the issue specifies.
  assert.match(text, /text-red-400/);
  assert.match(text, /text-yellow-400/);
  assert.match(
    text,
    /case\s+['"]debug['"]:\s*return\s*['"]text-gray-500 italic['"]/,
  );
});


test("ConsolePanel imports the autocomplete helper locally", () => {
  const text = readText(consolePanelPath);
  // The panel must import the dictionary from the config module
  // (per MODULE_SYSTEM_ROADMAP.md's "no machine constants in
  // components" rule).
  assert.match(
    text,
    /import\s*\{[^}]*filterAutocompleteCommands[^}]*\}\s*from\s*['"]\.\.\/config\/gcodes['"]/,
  );
});
