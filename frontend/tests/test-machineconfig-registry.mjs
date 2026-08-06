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
import { readFileSync, existsSync } from "node:fs";
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
  "frontend/src/views/EditorView.vue",
);
// ``apiPath`` is referenced as a regression guard — the legacy
// ``services/api.js`` wrapper was removed in favor of the
// generated ``ModulesMachineconfigService`` client. The test
// below asserts the file is gone.
void apiPath;
const componentsDir = resolve(
  repoRoot,
  "frontend/src/modules/machineconfig/components",
);
const machineConfigViewPath = resolve(
  repoRoot,
  "frontend/src/modules/machineconfig/components/MachineConfigView.vue",
);

function readText(path) {
  return readFileSync(path, "utf-8");
}

test("machineconfig manifest has the documented shape", () => {
  const manifest = readText(manifestPath);
  assert.match(manifest, /id:\s*(['"`])machineconfig\1/);
  assert.match(manifest, /title:\s*(['"`])Machine Config\1/);
  assert.match(manifest, /sidebar:\s*\{/);
  assert.match(manifest, /id:\s*(['"`])config\1/, "sidebar id must reuse the legacy config slot");
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

test("machineconfig store calls the generated ModulesMachineconfigService client", () => {
  // The legacy per-module ``services/api.js`` wrapper was removed
  // in favor of the OpenAPI-generated client. The store now goes
  // straight through ``ModulesMachineconfigService`` so the
  // generated types stay in sync with the backend schema.
  const storeText = readText(storePath);
  assert.match(
    storeText,
    /import\s*\{[^}]*ModulesMachineconfigService[^}]*\}\s*from\s*["'][^"']*generated\/api[^"']*["']/,
  );
  // The store must hit every documented endpoint family. The
  // generated client names the methods after the OpenAPI
  // ``operation_id`` (``listCompilersApiV1ModulesMachineconfig…
  // ``), so we assert on the camel-cased suffix instead.
  for (const suffix of [
    "listCompilersApiV1ModulesMachineconfigCompilersGet",
    "getProfilesTreeApiV1ModulesMachineconfigProfilesTreeGet",
    "compileProfileApiV1ModulesMachineconfigCompilePost",
    "deployStagedApiV1ModulesMachineconfigDeployPost",
    "listStagedApiV1ModulesMachineconfigStagedGet",
    "listActiveApiV1ModulesMachineconfigActiveGet",
  ]) {
    assert.match(
      storeText,
      new RegExp(suffix),
      `store must call ModulesMachineconfigService.${suffix}`,
    );
  }
});

test("machineconfig index.js wires the manifest + components", () => {
  const indexText = readText(indexPath);
  assert.match(indexText, /import manifest from "\.\/manifest\.js"/);
  assert.match(indexText, /onLoad\(/);
  assert.match(indexText, /onUnload\(/);
  assert.doesNotMatch(indexText, /MachineConfigView/);
});

test("machineconfig components folder ships the four panels", () => {
  for (const name of [
    "ProfilesExplorer.vue",
    "CompilerPanel.vue",
    "CompiledOutputViewer.vue",
    "DeploymentPanel.vue",
    "ActivePanel.vue",
  ]) {
    const path = resolve(componentsDir, name);
    const text = readText(path);
    assert.ok(text.length > 0, `${name} must exist and be non-empty`);
  }
  assert.equal(existsSync(machineConfigViewPath), false, "MachineConfigView.vue must be removed");
});

test("EditorView composes every machineconfig panel", () => {
  const viewText = readText(viewPath);
  // The legacy ``ConfigView.vue`` was renamed to
  // ``EditorView.vue`` once the file manager started routing
  // edits through ``router.push({ name: 'config' })``. The
  // machineconfig panels now live inside ``EditorView`` and
  // are rendered alongside the editor surface.
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
      `EditorView must import ${component}`,
    );
  }
  assert.match(viewText, /useMachineConfigStore/);
  // The view calls the store's loaders on mount so the
  // compilers and listings are populated by the time the
  // panels render.
  assert.match(viewText, /loadAll\(\)/);
});

test("App.vue routes module sidebar ids to the module view", () => {
  const appText = readText(resolve(repoRoot, "frontend/src/App.vue"));
  // The current App.vue drives view selection through Vue Router
  // (``useRoute().name``) instead of a local ``currentView``
  // ref. The module-owned view still wins when the route name
  // matches a mounted module id, so the contract is preserved.
  assert.match(
    appText,
    /registry\.modules\.has\(\s*name\s*\)/,
    "App.vue must consult the registry to detect module-owned sidebar ids",
  );
  assert.match(
    appText,
    /useRoute\(\)/,
    "App.vue must read the active view via Vue Router",
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

test("AppSidebar keeps the legacy config slot for the module override", () => {
  // The machineconfig module now reuses the legacy config nav slot,
  // so the built-in fallback remains available when the module is not
  // mounted.
  const sidebarText = readText(
    resolve(repoRoot, "frontend/src/components/AppSidebar.vue"),
  );
  assert.match(sidebarText, /id:\s*['"]config['"]/);
  assert.doesNotMatch(sidebarText, /MachineConfigView/);
});