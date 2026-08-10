// Frontend module-registry tests for the macros module.
//
// Run with: node --test frontend/tests/test-macros-registry.mjs
//
// The macros module ships:
//   * a dashboard panel (``MacroPanel.vue`` — list + Run buttons),
//   * a dashboard M-code panel (``McodePanel.vue``),
//   * a Machine Config → Macros tab (``MacroManagerPanel.vue`` —
//     handles ``.macro`` AND ``.ngc`` kinds via a single
//     flat list with a kind picker on the Create dialog),
//   * a Machine Config → M-codes sub-panel
//     (``McodeManagerPanel.vue`` — drives the universal editor),
//   * a Pinia store fronting the generated ``ModulesMacrosService``,
//   * a kind-aware validator (one regex for ``.macro``/``.ngc``,
//     one range regex for M-codes),
//   * a JS port of the backend macro parser (used only for the
//     ``.macro`` Run path),
//   * a Universal-editor m-code branch so ``/config/M101`` opens
//     in the existing editor.
//
// This test mirrors ``test-machineconfig-registry.mjs`` — it guards
// the static shape of the new module and the wiring into
// ``DashboardView`` / ``EditorView`` without spinning up Vue / Pinia.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");

const manifestPath = resolve(
  repoRoot,
  "frontend/src/modules/macros/manifest.js",
);
const storePath = resolve(repoRoot, "frontend/src/modules/macros/store.js");
const indexPath = resolve(repoRoot, "frontend/src/modules/macros/index.js");
const parserPath = resolve(repoRoot, "frontend/src/modules/macros/parser.js");

const dashboardPath = resolve(
  repoRoot,
  "frontend/src/views/DashboardView.vue",
);
const editorViewPath = resolve(
  repoRoot,
  "frontend/src/views/EditorView.vue",
);
const editorStorePath = resolve(
  repoRoot,
  "frontend/src/stores/editor.js",
);

const componentsDir = resolve(
  repoRoot,
  "frontend/src/modules/macros/components",
);

function readText(path) {
  return readFileSync(path, "utf-8");
}

test("macros manifest has the documented shape", () => {
  const manifest = readText(manifestPath);
  assert.match(manifest, /id:\s*(['"`])macros\1/);
  assert.match(manifest, /title:\s*(['"`])Macros\1/);
  assert.match(manifest, /settingsPanel:\s*true/);
  // No sidebar; both surfaces live on the dashboard + Machine
  // Config column. The previous attempt at a sidebar entry was
  // rolled back when the user said this module's UI sits in
  // those two places.
  assert.doesNotMatch(manifest, /sidebar:\s*\{/);
});

test("macros store id follows the module_ prefix rule", () => {
  const storeText = readText(storePath);
  assert.match(
    storeText,
    /const\s+STORE_ID\s*=\s*`module_\$\{manifest\.id\}`/,
    "store must build its id from module_${manifest.id}",
  );
  assert.match(storeText, /defineStore\(\s*STORE_ID/);
});

test("macros store imports ModulesMacrosService from the generated client", () => {
  const storeText = readText(storePath);
  // The regex deliberately does not anchor on the first ``{...}``
  // brace pair — the store has multiple ``import`` statements and
  // we only need the right one anywhere in the file.
  assert.match(
    storeText,
    /\bModulesMacrosService\b/,
  );
  assert.match(storeText, /\bgenerated\/api\b/);
  // The dashboard "Run" path dispatches each static block line as
  // an MDI command via the machine module, so both generated
  // services must be reachable from the store.
  assert.match(storeText, /\bModulesMachineService\b/);
});

test("macros store calls every documented macro endpoint", () => {
  const storeText = readText(storePath);
  for (const suffix of [
    "listMacros",
    "readMacro",
    "writeMacro",
    "deleteMacro",
  ]) {
    assert.match(
      storeText,
      new RegExp(`\\b${suffix}\\(`),
      `store must call ModulesMacrosService.${suffix}`,
    );
  }
});

test("macros store wires actions to take a kind argument", () => {
  // Every action that touches the backend must declare a ``kind``
  // parameter so the ``?kind=`` query goes through. The store's
  // ``MACRO_KIND`` enum keeps callers consistent.
  const storeText = readText(storePath);
  assert.match(
    storeText,
    /export\s+const\s+MACRO_KIND\s*=\s*Object\.freeze\(/,
  );
  // Object literal keys use ``MACRO:`` not ``macro:``, but the
  // *values* are the lower-case tokens. Look for the value
  // strings inside the freeze block.
  assert.match(storeText, /MACRO:\s*['"]macro['"]/, "MACRO_KIND must include 'macro'");
  assert.match(storeText, /NGC:\s*['"]ngc['"]/, "MACRO_KIND must include 'ngc'");
  assert.match(storeText, /MCODE:\s*['"]mcode['"]/, "MACRO_KIND must include 'mcode'");
  // ``loadList(kind)`` etc. carry the kind through. Spot-check by
  // checking that ``readMacro`` takes two parameters (kind, name).
  for (const fn of ["readMacro", "saveMacro", "deleteMacro"]) {
    assert.match(
      storeText,
      new RegExp(`function\\s+${fn}\\(\\s*kind`),
      `${fn} must declare kind as its first parameter`,
    );
  }
});

test("macros store keeps per-kind listing refs so loadList never empties siblings", () => {
  // Bug guard: ``loadList(kind)`` previously assigned to a single
  // shared ``macros`` ref, which meant mounting the M-code panel
  // after the macro/ngc panels emptied both listings. The fix is
  // three per-kind refs (``macroFiles`` / ``ngcFiles`` /
  // ``mcodeFiles``); each ``loadList(kind)`` writes into its own
  // container. ``store.macros`` must no longer exist.
  const storeText = readText(storePath);
  assert.match(
    storeText,
    /\b(?:const|let|var)\s+macroFiles\s*=\s*ref\(\s*\[\s*\]/,
    "store must declare a macroFiles ref",
  );
  assert.match(
    storeText,
    /\b(?:const|let|var)\s+ngcFiles\s*=\s*ref\(\s*\[\s*\]/,
    "store must declare an ngcFiles ref",
  );
  assert.match(
    storeText,
    /\b(?:const|let|var)\s+mcodeFiles\s*=\s*ref\(\s*\[\s*\]/,
    "store must declare an mcodeFiles ref",
  );
  // The old single ref must be gone — if a future refactor
  // regresses to a shared array, this assertion trips first.
  assert.doesNotMatch(
    storeText,
    /\b(?:const|let|var)\s+macros\s*=\s*ref\(\s*\[\s*\]/,
    "store must not declare a shared `macros` ref (regression)",
  );
  // ``loadList`` writes to one of the per-kind refs via the
  // ``listRefFor`` dispatch table, never into a bare ``macros``.
  assert.match(
    storeText,
    /listRefFor\(\s*kind\s*\)/,
    "loadList must dispatch through the per-kind ref table",
  );
  // The public surface replaces ``macros`` with three refs.
  assert.match(storeText, /\bmacroFiles\b/);
  assert.match(storeText, /\bngcFiles\b/);
  assert.match(storeText, /\bmcodeFiles\b/);
});

test("macros store exposes the run-via-MDI action", () => {
  const storeText = readText(storePath);
  for (const symbol of [
    "runMacro",
    "runMacroOfKind",
    "loadList",
    "saveMacro",
    "deleteMacro",
    "loadAll",
  ]) {
    assert.match(
      storeText,
      new RegExp(`\\b${symbol}\\b`),
      `store must export ${symbol}`,
    );
  }
  // ``runMacro`` must import the parser so the dispatch path
  // stays self-contained inside the store.
  assert.match(storeText, /import\s*\{[^}]*parseMacro[^}]*\}\s*from\s*["'][^"']*parser\.js["']/);
});

test("macros index.js wires the manifest + four components + settingsPanel", () => {
  const indexText = readText(indexPath);
  assert.match(indexText, /import manifest from "\.\/manifest\.js"/);
  assert.match(indexText, /onLoad\(/);
  assert.match(indexText, /onUnload\(/);
  // All four components are imported and re-exported.
  for (const name of ["MacroPanel", "MacroManagerPanel", "McodePanel", "McodeManagerPanel"]) {
    assert.match(indexText, new RegExp(`\\bimport\\s+${name}\\b`));
    assert.match(indexText, new RegExp(`\\b${name}\\b`));
  }
  // ``settingsPanel`` exposes the manager panel for the future
  // Settings view.
  assert.match(indexText, /settingsPanel:\s*MacroManagerPanel/);
});

test("macros components folder ships the four documented components", () => {
  for (const name of [
    "MacroPanel.vue",
    "MacroManagerPanel.vue",
    "McodePanel.vue",
    "McodeManagerPanel.vue",
  ]) {
    const path = resolve(componentsDir, name);
    assert.ok(existsSync(path), `${name} must exist`);
    const text = readText(path);
    assert.ok(text.length > 0, `${name} must be non-empty`);
  }
});

test("macros parser exports parseMacro and MacroParseError", () => {
  const parserText = readText(parserPath);
  assert.match(parserText, /export\s+(class|function)\s+parseMacro\b/);
  assert.match(parserText, /export\s+class\s+MacroParseError\b/);
  // Same regex boundary as ``MacroStorage._validate`` on the
  // backend for ``.macro`` / ``.ngc`` names.
  assert.match(parserText, /\^\[A-Za-z0-9\._-\]\{1,64\}\$/);
});

test("macros parser exports the M-code name regex", () => {
  const parserText = readText(parserPath);
  // ``MCODE_NAME_REGEX`` mirrors ``MCodeFileService.MCODE_NAME``
  // on the backend — M100..M199 inclusive. The actual source
  // contains ``/^M1\\d{2}$/``; we search for the literal as it
  // appears, no clever regex needed.
  assert.match(parserText, /MCODE_NAME_REGEX\s*=\s*\/\^M1\\d\{2\}\$\//);
  // ``validateMacroKindName`` accepts the kind-specific branches.
  assert.match(
    parserText,
    /export\s+function\s+validateMacroKindName\b/,
  );
});

test("DashboardView mounts MacroPanel + McodePanel via the registry shim", () => {
  const dashboardText = readText(dashboardPath);
  // Both panels are wired through the same nullable
  // ``panelFor(<id>, <Component>)`` shape used by the rest of the
  // dashboard.
  assert.match(
    dashboardText,
    /panelFor\(\s*['"]macros['"]\s*,\s*['"]MacroPanel['"]\s*\)/,
    "DashboardView must register MacroPanel via panelFor('macros', 'MacroPanel')",
  );
  assert.match(
    dashboardText,
    /panelFor\(\s*['"]macros['"]\s*,\s*['"]McodePanel['"]\s*\)/,
    "DashboardView must register McodePanel via panelFor('macros', 'McodePanel')",
  );
  // Reactive ``registry.modules.has('macros')`` gate so the panels
  // hide cleanly when the module is unmounted.
  assert.match(
    dashboardText,
    /registry\.modules\.has\(\s*['"]macros['"]\s*\)/,
    "DashboardView must gate macro panels on registry.modules.has('macros')",
  );
  assert.match(dashboardText, /<MacroPanel\s+v-if="macrosMounted"\s*\/>/);
  assert.match(dashboardText, /<McodePanel\s+v-if="macrosMounted"\s*\/>/);
});

test("EditorView renders MacroManagerPanel + McodeManagerPanel in the right column", () => {
  const editorText = readText(editorViewPath);
  assert.match(
    editorText,
    /import\s+MacroManagerPanel\s+from\s+['"][^'"]*modules\/macros\/components\/MacroManagerPanel\.vue['"]/,
  );
  assert.match(
    editorText,
    /import\s+McodeManagerPanel\s+from\s+['"][^'"]*modules\/macros\/components\/McodeManagerPanel\.vue['"]/,
  );
  // Manager panels sit in the right column alongside
  // ``ActivePanel``; the rest of the machineconfig grid is
  // preserved verbatim.
  assert.match(
    editorText,
    /xl:col-span-8[\s\S]*?<ActivePanel\s*\/>[\s\S]*?<MacroManagerPanel\s*\/>/,
    "EditorView must render MacroManagerPanel inside the xl:col-span-8 section, below ActivePanel",
  );
  assert.match(
    editorText,
    /xl:col-span-8[\s\S]*?<McodeManagerPanel\s*\/>/,
    "EditorView must render McodeManagerPanel inside the xl:col-span-8 section",
  );
});

test("universal-editor isProfilePath routes bare M-codes through machineconfig", () => {
  const text = readText(editorStorePath);
  // The new branch in ``isProfilePath`` accepts the
  // ``^M1\d{2}$`` shape (regex literal ``/^M1\\d{2}$/``).
  assert.match(text, /MCODE_NAME_PATTERN\s*=\s*\/\^M1\\d\{2\}\$\//);
  assert.match(text, /MCODE_NAME_PATTERN\.test\(\s*path\s*\)/);
  // ``readByPath`` / ``writeByPath`` dispatch to the
  // machineconfig ``readMCode`` / ``writeMCode`` methods. The
  // generated client methods are called with whitespace between
  // the service and the method name (different in Prettier's
  // formatting), so the regex accepts any whitespace.
  assert.match(text, /ModulesMachineconfigService\s*\.readMCode\b/);
  assert.match(text, /ModulesMachineconfigService\s*\.writeMCode\b/);
});

test("MacroManagerPanel offers both macro and ngc kinds in the Create dialog", () => {
  const managerPath = resolve(
    componentsDir,
    "MacroManagerPanel.vue",
  );
  const text = readText(managerPath);
  // The Create dialog has a kind radio with both values. Vue
  // template syntax writes ``value="macro"`` (no JS colon), hence
  // the simpler pattern than the test for the manager's own
  // store.
  assert.match(text, /value=['"]macro['"]/);
  assert.match(text, /value=['"]ngc['"]/);
  // The dialog calls ``validateMacroKindName(kind, name)`` so a
  // typo surfaces before the backend round-trip.
  assert.match(text, /validateMacroKindName\(\s*createKind\.value\s*,\s*name\s*\)/);
});

test("MacroPanel reads from the per-kind macroFiles + ngcFiles refs (regression)", () => {
  // Bug guard: ``MacroPanel.vue`` previously read from the shared
  // ``store.macros`` ref. Mount-order races with ``McodePanel``
  // could empty it. The fix is to read only from the two refs
  // the dashboard owns.
  const panelPath = resolve(componentsDir, "MacroPanel.vue");
  const text = readText(panelPath);
  assert.match(
    text,
    /\bmacroFiles\b/,
    "MacroPanel must reference macroFiles",
  );
  assert.match(
    text,
    /\bngcFiles\b/,
    "MacroPanel must reference ngcFiles",
  );
  // Both refs must come from the per-kind store. We accept both
  // the destructure form (``const { macroFiles, ngcFiles } =
  // storeToRefs(store)``) and the explicit form to keep the
  // test honest across minor code reshuffles.
  assert.match(
    text,
    /(?:\{[^}]*\bmacroFiles\b[^}]*\}\s*=\s*storeToRefs\(store\)|\bmacroFiles\s*=\s*storeToRefs\(store\))/,
    "macroFiles must come from storeToRefs(store)",
  );
  assert.match(
    text,
    /(?:\{[^}]*\bngcFiles\b[^}]*\}\s*=\s*storeToRefs\(store\)|\bngcFiles\s*=\s*storeToRefs\(store\))/,
    "ngcFiles must come from storeToRefs(store)",
  );
  // Old shape with shared ``macros`` must be gone.
  assert.doesNotMatch(
    text,
    /\b(?:const|let|var)\s+\{[^}]*\bmacros\b[^}]*\}\s*=\s*storeToRefs/,
    "MacroPanel must not use the shared macros ref (regression)",
  );
});

test("McodePanel reads only from mcodeFiles (regression)", () => {
  // M-code panel must read from the mcode-only ref; cross-kind
  // leaks would double-render and confuse the operator.
  const panelPath = resolve(componentsDir, "McodePanel.vue");
  const text = readText(panelPath);
  assert.match(
    text,
    /(?:\{[^}]*\bmcodeFiles\b[^}]*\}\s*=\s*storeToRefs\(store\)|\bmcodeFiles\s*=\s*storeToRefs\(store\))/,
    "mcodeFiles must come from storeToRefs(store)",
  );
  // ``McodePanel`` must not consult ``macroFiles`` / ``ngcFiles``
  // either — those are owned by MacroPanel / MacroManagerPanel.
  assert.doesNotMatch(text, /\bmacroFiles\b/);
  assert.doesNotMatch(text, /\bngcFiles\b/);
});

test("McodeManagerPanel uses the M-code name regex from the parser", () => {
  const managerPath = resolve(
    componentsDir,
    "McodeManagerPanel.vue",
  );
  const text = readText(managerPath);
  // The component shows the regex to the operator so the
  // constraint is discoverable without reading the source.
  assert.match(text, /MCODE_NAME_REGEX/);
  // Naming an M-code just creates the file. The Edit button
  // deep-links to the universal editor instead of opening a
  // local CodeMirror modal — one editor surface for every kind.
  assert.match(text, /router\.push\(\{\s*name:\s*['"]config['"]/);
  assert.match(text, /filename:\s*name\s*\}/);
});

test("MacroManagerPanel normalises empty bodies to avoid the FastAPI 422", () => {
  // FastAPI rejects a zero-byte text/plain body with 422. The
  // store seeds ``"\n"`` for new macros and the management panel
  // follows the same pattern for both ``.macro`` and ``.ngc``
  // Create dialogs.
  const managerPath = resolve(
    componentsDir,
    "MacroManagerPanel.vue",
  );
  const text = readText(managerPath);
  assert.match(
    text,
    /commitCreate[\s\S]*?saveMacro\([\s\S]*?["']\\n["']\)/,
    "commitCreate must seed the new macro body with a non-empty placeholder",
  );
});

test("McodeManagerPanel normalises empty bodies the same way", () => {
  const managerPath = resolve(
    componentsDir,
    "McodeManagerPanel.vue",
  );
  const text = readText(managerPath);
  assert.match(
    text,
    /commitCreate[\s\S]*?saveMacro\([\s\S]*?["']\\n["']\)/,
    "McodeManagerPanel's commitCreate must seed the new M-code body with a non-empty placeholder",
  );
});
