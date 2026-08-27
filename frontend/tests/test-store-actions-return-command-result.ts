// Structural guard: every manual-trigger store action must return
// ``Promise<CommandResult>``. Pinpoints any future reintroduction of
// the ``!result.success`` typo class — the only way to add a manual
// action is to type it.
//
// Reads (``loadList`` / ``readMacro`` / ``ensureMacroContent`` etc.)
// keep their legacy return shape (string|null, array, …) and are
// allow-listed below.
//
// Run with: ``node --test frontend/tests/test-store-actions-return-command-result.mjs``

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { resolve, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");

const FRONTEND_DIR = resolve(repoRoot, "frontend");
const STORES_DIR = resolve(FRONTEND_DIR, "src/stores");

const ALLOWED_READ_NAMES = new Set([
  // Pinia pattern — return the store implementation itself.
  "useMachineStore",
  "useBaseThreadStore",
  "useMacrosStore",
  "useMachineConfigStore",
  // Reads that legitimately don't return a CommandResult.
  "loadList",
  "loadAll",
  "readMacro",
  "ensureMacroContent",
  "loadCompilers",
  "loadProfilesTree",
  "loadStaged",
  "loadActive",
  "readProfileContent",
  "readStagedFileContent",
  "readActiveFileContent",
  "list",
  // Selectors / sub-state accessors.
  "selectProfile",
  "refreshSettings",
  // WebSocket-only — fire-and-forget keep-alive, no request/response.
  "jog",
  "jogContinuous",
  "jogStop",
  // Telemetry refresh — not a manual trigger.
  "refreshStreamMessage",
  // Module mount lifecycle hooks.
  "setup",
  "teardown",
  "init",
  "destroy",
  // Pinia refs returned via helpers — read-only views.
  "useToolRefs",
  "useMachineRefs",
  "useConsoleStore",
  "useToastStore",
]);

function walk(dir) {
  const out = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      out.push(...walk(full));
    } else if (/[Ss]tore\.ts$/.test(entry)) {
      // Match ``fooStore.ts`` (Pinia store) but skip ``fooTypes.ts``
      // (plain type-only file).
      out.push(full);
    }
  }
  return out;
}

function extractExportedAsyncFunctions(text) {
  // Capture ``export const name =`` and ``async function name(`` /
  // ``async ( ... ) => ...`` patterns emitted by Pinia
  // ``defineStore`` setup factories.
  const names = new Set();
  const re = /(?:async\s+function\*?\s*([A-Za-z_$][\w$]*)|const\s+([A-Za-z_$][\w$]*)\s*=\s*async\s*(?:\(|\[|function))/g;
  let match;
  while ((match = re.exec(text))) {
    const name = match[1] || match[2];
    if (name) names.add(name);
  }
  return names;
}

function isReExportModule(text) {
  // Bare re-export module: ``export { name } from "..."`` /
  // ``export { name1, name2 } from "..."`` with no other code.
  // The ``store.ts`` skeleton files in some module directories
  // forward to a real store and have no async functions of their own.
  const stripped = text.replace(/^export\s*\{[^}]*\}\s*from\s*["'][^"']+["'];?\s*$/m, "");
  return stripped.replace(/\s/g, "").length <= stripped.length;
}

const storePaths = walk(STORES_DIR);

test("every store file has at least one async function (sanity)", () => {
  assert.ok(storePaths.length > 0, "no store files found");
  for (const p of storePaths) {
    const text = readFileSync(p, "utf-8");
    if (isReExportModule(text)) continue;
    const fns = extractExportedAsyncFunctions(text);
    assert.ok(
      fns.size > 0,
      `${p.replace(repoRoot + "\\", "")} has no async functions`,
    );
  }
});

test("manual-trigger actions return Promise<CommandResult>", () => {
  // Allow-list of names that match action verbs but legitimately
  // don't need to return a CommandResult (WebSocket-only jog path,
  // pure-refresh lifecycle hooks, etc.). Anything outside this list
  // that matches the action-verb regex must type its return as
  // ``Promise<CommandResult>``.
  const verbs = /^(set|toggle|home|start|stop|pause|resume|abort|run|load|unload|save|delete|update|upload|deploy|compile|rename|createFolder|createFile|reload|refresh|move|copy|reset|enable|disable|trigger|request|cancel|mark|clear|pick|archive|restore|apply|commit|promote|demote|swap|send|dispatch)$/i;

  for (const p of storePaths) {
    const text = readFileSync(p, "utf-8");
    if (isReExportModule(text)) continue;
    const fns = [...extractExportedAsyncFunctions(text)];

    for (const name of fns) {
      if (!verbs.test(name as string)) continue;
      if (ALLOWED_READ_NAMES.has(name as string)) continue;

      // Look for a return type annotation that promises CommandResult.
      // Accepted forms: ``: Promise<CommandResult>``, ``Promise<CommandResult | ...>``,
      // ``Promise<CommandResult | null>``, ``Promise<CommandResult | undefined>``.
      // The setup-factory pattern emits ``Promise<CommandResult>``
      // when the future author types it correctly; bare ``async ()``
      // without an annotation trips the gate.
      const sig = new RegExp(
        `(?:async\\s+(?:function\\b)?\\s*${name}\\b|const\\s+${name}\\s*=\\s*async)[^{;]*?Promise\\s*<\\s*CommandResult\\b`,
        "m",
      );
      assert.ok(
        sig.test(text),
        `${p.replace(repoRoot + "\\", "")} :: ${name} must declare Promise<CommandResult> as its return type (the only way the UI gets a uniform response)`,
      );
    }
  }
});

test("machineStore exposes run/unload/pause/resume/abort programs (regression guard)", () => {
  // Regression guard for the ActivePrintWidget migration: the
  // machine store must expose every lifecycle action that the
  // widget calls.
  const text = readFileSync(resolve(STORES_DIR, "machine.ts"), "utf-8");
  for (const fn of [
    "loadProgram",
    "runProgram",
    "unloadProgram",
    "pauseProgram",
    "resumeProgram",
    "abortProgram",
  ]) {
    const sig = new RegExp(
      `(?:async\\s+(?:function\\b)?\\s*${fn}\\b|const\\s+${fn}\\s*=\\s*async)[^{;]*?Promise\\s*<\\s*CommandResult`,
      "m",
    );
    assert.ok(sig.test(text), `useMachineStore.${fn} must return Promise<CommandResult>`);
  }
});

test("reportCommandFailure is the single chokepoint for failure messages", () => {
  // Every ``consoleStore.error`` call inside a store action that
  // funnels through ``reportCommandFailure`` must include
  // ``{popup: true}`` (toast). Manual triggers route failures
  // through the helper; only the helper sets ``popup: true``.
  const errPath = resolve(FRONTEND_DIR, "src/core/error-format.ts");
  const helperText = readFileSync(errPath, "utf-8");
  assert.match(
    helperText,
    /useConsoleStore\(\)\.error\([^)]*popup:\s*true/,
    "reportCommandFailure must emit via consoleStore.error with popup:true",
  );

  // Stores should not hand-roll ``consoleStore.error(`Failed to <name>``)
  // lines for actions that go through the helper — they should
  // call the helper instead. Spot-check that stores use it.
  const machineText = readFileSync(resolve(STORES_DIR, "machine.ts"), "utf-8");
  assert.match(
    machineText,
    /reportCommandFailure\(/,
    "useMachineStore must import and use reportCommandFailure",
  );

  const macrosText = readFileSync(
    resolve(STORES_DIR, "macrosStore.ts"),
    "utf-8",
  );
  assert.match(
    macrosText,
    /reportCommandFailure\(/,
    "useMacrosStore must import and use reportCommandFailure",
  );

  const machineConfigText = readFileSync(
    resolve(STORES_DIR, "machineconfigStore.ts"),
    "utf-8",
  );
  assert.match(
    machineConfigText,
    /reportCommandFailure\(/,
    "useMachineConfigStore must import and use reportCommandFailure",
  );
});
