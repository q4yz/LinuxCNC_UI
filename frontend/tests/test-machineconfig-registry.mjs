// Frontend module-registry tests for the machineconfig module.
//
// Run with: node --test frontend/tests/test-machineconfig-registry.mjs
//
// The machineconfig module owns the new Machine Configuration,
// Compilation, and Deployment surface (issue #41). The static
// checks below guard:
//
//   * manifest shape (id / title / sidebar / settingsPanel),
//   * store id matches ``module_<manifest.id>``,
//   * the module entrypoint exports the four panels + the view,
//   * the store wires the API surface (loaders + actions),
//   * the sidebar entry id agrees with the manifest id so the
//     AppSidebar + App.vue route the click correctly.
//
// The Pinia store is loaded via a hand-written manifest mirror
// rather than a dynamic import because the store factory pulls in
// ``../../stores/console.js`` which depends on Pinia — the same
// trick used by ``tests/test-machine-registry.mjs``.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");

const manifestPath = resolve(
  repoRoot,
  "frontend/src/modules/machineconfig/manifest.js",
);
const storePath = resolve(
  repoRoot,
  "frontend/src/modules/machineconfig/store.js",
);
const indexPath = resolve(
  repoRoot,
  "frontend/src/modules/machineconfig/index.js",
);
const apiPath = resolve(
  repoRoot,
  "frontend/src/modules/machineconfig/services/api.js",
);
const viewPath = resolve(
  repoRoot,
  "frontend/src/modules/machineconfig/components/MachineConfigView.vue",
);
const componentsDir = resolve(
  repoRoot,
  "frontend/src/modules/machineconfig/components",
);

function readText(path) {
  return readFileSync(path, "utf-8");
}

test("machineconfig manifest has the documented shape", () => {
  const manifest = readText(manifestPath);
  assert.match(manifest, /id:\s*(['"`])machineconfig\1/);
  assert.match(manifest, /title:\s*(['"`])Machine Config\1/);
  assert.match(manifest, /sidebar:\s*\{/);
  assert.match(manifest, /id:\s*(['"`])machineconfig\1/, "sidebar id matches manifest id");
  assert.match(manifest, /label:\s*(['"`])Machine Config\1/);
  assert.match(manifest, /order:\s*60/);
  assert.match(manifest, /settingsPanel:\s*true/);
});

test("machineconfig store id follows the module_ prefix rule", () => {
  const storeText = readText(storePath);
  // Pinia store id is built from ``module_${manifest.id}``.
  assert.match(
    storeText,
    /const\s+STORE_ID\s*=\s*`module_\$\{manifest\.id\}`/,
    "store must build its id from module_${manifest.id}",
  );
  assert.match(storeText, /defineStore\(\s*STORE_ID/);
});

test("machineconfig store exports the standard surface", () => {
  const storeText = readText(storePath);
  for (const symbol of [
    "useMachineConfigStore",
    "useMachineConfigRefs",
    "loadCompilers",
    "loadProfilesTree",
    "loadStaged",
    "loadActive",
    "loadAll",
    "selectProfile",
    "readProfileContent",
    "saveProfile",
    "createFolder",
    "createFile",
    "renameProfile",
    "deleteProfile",
    "compile",
    "deploy",
    "readStagedFileContent",
    "readActiveFileContent",
  ]) {
    assert.match(
      storeText,
      new RegExp(`\\b${symbol}\\b`),
      `store must export ${symbol}`,
    );
  }
});

test("machineconfig API wrapper targets the module URL", () => {
  const apiText = readText(apiPath);
  assert.match(apiText, /\/api\/v1\/modules\/machineconfig\//);
  // The wrapper must surface every documented endpoint.
  for (const fn of [
    "listCompilers",
    "listProfilesTree",
    "readProfile",
    "saveProfile",
    "createFolder",
    "createFile",
    "renameProfile",
    "deleteProfile",
    "compileProfile",
    "deployStaged",
    "listStaged",
    "readStagedContent",
    "listActive",
    "readActiveContent",
    "readMachineName",
  ]) {
    assert.match(
      apiText,
      new RegExp(`export\\s+function\\s+${fn}\\b`),
      `api wrapper must export ${fn}`,
    );
  }
});

test("machineconfig index.js wires the manifest + components", () => {
  const indexText = readText(indexPath);
  assert.match(indexText, /import manifest from "\.\/manifest\.js"/);
  assert.match(indexText, /import MachineConfigView from "\.\/components\/MachineConfigView\.vue"/);
  assert.match(indexText, /onLoad\(/);
  assert.match(indexText, /onUnload\(/);
  // The components map must surface MachineConfigView so the
  // App.vue's lazy loader can pick it up.
  assert.match(indexText, /components:\s*\{/);
  assert.match(indexText, /MachineConfigView/);
});

test("machineconfig components folder ships the four panels + view", () => {
  for (const name of [
    "ProfilesExplorer.vue",
    "CompilerPanel.vue",
    "CompiledOutputViewer.vue",
    "DeploymentPanel.vue",
    "ActivePanel.vue",
    "MachineConfigView.vue",
  ]) {
    const path = resolve(componentsDir, name);
    const text = readText(path);
    assert.ok(text.length > 0, `${name} must exist and be non-empty`);
  }
});

test("MachineConfigView composes every panel", () => {
  const viewText = readText(viewPath);
  for (const component of [
    "ProfilesExplorer",
    "CompilerPanel",
    "CompiledOutputViewer",
    "DeploymentPanel",
    "ActivePanel",
  ]) {
    assert.match(
      viewText,
      new RegExp(`import\\s+${component}\\s+from`),
      `MachineConfigView must import ${component}`,
    );
  }
});

test("App.vue routes module sidebar ids to the module view", () => {
  const appText = readText(resolve(repoRoot, "frontend/src/App.vue"));
  assert.match(
    appText,
    /registry\.modules\.has\(currentView\.value\)/,
    "App.vue must consult the registry to detect module-owned sidebar ids",
  );
  assert.match(
    appText,
    /\.\/modules\/\*\/(components|components\/\*\.vue)/,
    "App.vue must lazily load module views via import.meta.glob",
  );
  assert.match(
    appText,
    /<component\s+v-if="moduleView"\s+:is="moduleView"\s*\/>/,
    "App.vue must render the resolved module view via <component :is>",
  );
});

test("AppSidebar no longer ships the legacy config builtin", () => {
  // The new machineconfig module's sidebar entry supersedes the
  // legacy "Machine Config" button. The legacy ConfigView still
  // exists for direct-URL access, but the rail should not show
  // two near-identical buttons.
  const sidebarText = readText(
    resolve(repoRoot, "frontend/src/components/AppSidebar.vue"),
  );
  // The builtins list contains only Dashboard / G-Code Files /
  // Settings. The machineconfig module contributes its own entry.
  assert.doesNotMatch(
    sidebarText,
    /id:\s*['"]config['"]\s*,\s*label:\s*['"]Machine Config['"]/,
    "AppSidebar must not duplicate the machineconfig sidebar entry",
  );
});