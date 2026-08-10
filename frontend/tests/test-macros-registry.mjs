// Frontend module-registry tests for the macros module.
//
// Run with: node --test frontend/tests/test-macros-registry.mjs
//
// The macros module ships:
//   * a dashboard panel (``MacroPanel.vue`` — list + Run buttons),
//   * a Machine Config → Macros tab (``MacroManagerPanel.vue`` —
//     create / edit / delete),
//   * a Pinia store fronting the generated ``ModulesMacrosService``,
//   * a JS port of the backend macro parser,
//   * the run-via-MDI dispatch logic.
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
  // Modules with a sidebar would assert ``id: "macros"`` here. The
  // macros module deliberately omits one — the dashboard panel and
  // the EditorView tab strip cover both surfaces.
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
  assert.match(
    storeText,
    /import\s*\{[^}]*ModulesMacrosService[^}]*\}\s*from\s*["'][^"']*generated\/api[^"']*["']/,
  );
  // The dashboard "Run" path dispatches each static block line as
  // an MDI command via the machine module, so both generated
  // services must be reachable from the store.
  assert.match(
    storeText,
    /import\s*\{[^}]*ModulesMachineService[^}]*\}\s*from\s*["'][^"']*generated\/api[^"']*["']/,
  );
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

test("macros store exposes the run-via-MDI action", () => {
  const storeText = readText(storePath);
  for (const symbol of [
    "runMacro",
    "loadList",
    "saveMacro",
    "deleteMacro",
  ]) {
    assert.match(
      storeText,
      new RegExp(`\\b${symbol}\\b`),
      `store must export ${symbol}`,
    );
  }
  // ``runMacro`` must import the parser so the dispatch path stays
  // self-contained inside the store.
  assert.match(storeText, /import\s*\{[^}]*parseMacro[^}]*\}\s*from\s*["'][^"']*parser\.js["']/);
});

test("macros index.js wires the manifest + components + settingsPanel", () => {
  const indexText = readText(indexPath);
  assert.match(indexText, /import manifest from "\.\/manifest\.js"/);
  assert.match(indexText, /onLoad\(/);
  assert.match(indexText, /onUnload\(/);
  assert.match(indexText, /MacroPanel/);
  assert.match(indexText, /MacroManagerPanel/);
  // The settings-tab contract: the manager panel must be exposed
  // through ``settingsPanel`` so the future Settings view can render
  // it without a glob lookup.
  assert.match(indexText, /settingsPanel:\s*MacroManagerPanel/);
});

test("macros components folder ships the dashboard + manager panels", () => {
  for (const name of ["MacroPanel.vue", "MacroManagerPanel.vue"]) {
    const path = resolve(componentsDir, name);
    assert.ok(existsSync(path), `${name} must exist`);
    const text = readText(path);
    assert.ok(text.length > 0, `${name} must be non-empty`);
  }
});

test("macros parser.js exports parseMacro and MacroParseError", () => {
  const parserText = readText(parserPath);
  assert.match(parserText, /export\s+(class|function)\s+parseMacro\b/);
  assert.match(parserText, /export\s+class\s+MacroParseError\b/);
  // Same regex boundary as ``MacroStorage._validate`` on the backend.
  // The source contains the regex literal ``/^[A-Za-z0-9._-]{1,64}$/``;
  // we look for the raw, un-escaped form.
  assert.match(parserText, /\^\[A-Za-z0-9\._-\]\{1,64\}\$/);
});

test("DashboardView mounts MacroPanel via the registry shim", () => {
  const dashboardText = readText(dashboardPath);
  // The same ``panelFor(<id>, <Component>)`` pattern used for the
  // other modules.
  assert.match(
    dashboardText,
    /panelFor\(\s*['"]macros['"]\s*,\s*['"]MacroPanel['"]\s*\)/,
    "DashboardView must register MacroPanel via panelFor('macros', 'MacroPanel')",
  );
  // Reactive ``registry.modules.has('macros')`` gate so the panel
  // hides cleanly when the module is unmounted.
  assert.match(
    dashboardText,
    /registry\.modules\.has\(\s*['"]macros['"]\s*\)/,
    "DashboardView must gate MacroPanel on registry.modules.has('macros')",
  );
  // The panel sits inside the left column next to Tool / Jog.
  assert.match(dashboardText, /<MacroPanel\s+v-if="macrosMounted"\s*\/>/);
});

test("EditorView renders MacroManagerPanel inside the right machineconfig column", () => {
  const editorText = readText(editorViewPath);
  assert.match(
    editorText,
    /import\s+MacroManagerPanel\s+from\s+['"][^'"]*modules\/macros\/components\/MacroManagerPanel\.vue['"]/,
  );
  // Manager panel sits in the right column alongside ActivePanel;
  // the rest of the machineconfig grid is preserved verbatim.
  assert.match(
    editorText,
    /xl:col-span-8[\s\S]*?<ActivePanel\s*\/>[\s\S]*?<MacroManagerPanel\s*\/>/,
    "EditorView must render MacroManagerPanel inside the xl:col-span-8 section, below ActivePanel",
  );
  // The previous tab strip and ``activeConfigTab`` state were
  // removed when the macros manager moved into the right column.
  assert.doesNotMatch(editorText, /MACHINE_CONFIG_TABS/);
  assert.doesNotMatch(editorText, /activeConfigTab/);
  assert.doesNotMatch(editorText, /editor-config-tabs/);
});

test("MacroManagerPanel normalises empty bodies to avoid the FastAPI 422", () => {
  // FastAPI rejects a zero-byte text/plain body with 422. Seeded
  // with "\n" for new macros and rescued in saveEditor.
  const managerPath = resolve(
    repoRoot,
    "frontend/src/modules/macros/components/MacroManagerPanel.vue",
  );
  const text = readText(managerPath);
  // commitCreate seeds with a non-empty body.
  assert.match(
    text,
    /commitCreate[\s\S]*saveMacro\([^,]+,\s*["']\\n["']\)/,
    "commitCreate must seed the new macro body with a non-empty placeholder",
  );
  // saveEditor must guard against empty editor content.
  assert.match(
    text,
    /saveEditor[\s\S]*length\s*===\s*0\s*\?\s*["']\\n["']/,
    "saveEditor must normalise an empty body to a non-empty placeholder",
  );
});
