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
  "frontend/src/modules/machineconfig/manifest.ts",
);
const storePath = resolve(
  repoRoot,
  "frontend/src/modules/machineconfig/store.ts",
);
const indexPath = resolve(
  repoRoot,
  "frontend/src/modules/machineconfig/index.ts",
);
const apiPath = resolve(
  repoRoot,
  "frontend/src/modules/machineconfig/services/api.ts",
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
  // Sidebar id matches the manifest id so it doubles as the route
  // name. ``registerModuleRoutes`` reads this and builds the
  // ``/machineconfig`` route at boot. The legacy ``id: 'config'``
  // override that hijacked the built-in editor route is gone.
  assert.match(manifest, /id:\s*(['"`])machineconfig\1[,\s\n]/, "sidebar id must match the manifest id");
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

test("machineconfig index.js wires the manifest + mainView", () => {
  const indexText = readText(indexPath);
  assert.match(indexText, /import manifest from "\.\/manifest\.js"/);
  assert.match(indexText, /onLoad\(/);
  assert.match(indexText, /onUnload\(/);
  // ``mainView`` is the explicit top-level component the App shell
  // and ``registerModuleRoutes`` consult; it replaces the legacy
  // alphabetical glob discovery.
  assert.match(indexText, /MachineConfigView/);
  assert.match(indexText, /mainView:\s*MachineConfigView/);
});

test("machineconfig components folder ships the panels and the new view", () => {
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
  // MachineConfigView is the new top-level surface; the App shell
  // and ``registerModuleRoutes`` route ``/machineconfig`` to it.
  assert.equal(
    existsSync(machineConfigViewPath),
    true,
    "MachineConfigView.vue must be in place",
  );
});

test("MachineConfigView composes every panel", () => {
  const viewText = readText(machineConfigViewPath);
  for (const component of [
    "ProfilesExplorer",
    "CompilerPanel",
    "CompiledOutputViewer",
    "DeploymentPanel",
    "ActivePanel",
    "UpdateManager",
    "DebugPanel",
    "MacroManagerPanel",
    "McodeManagerPanel",
  ]) {
    assert.match(
      viewText,
      new RegExp(`import\\s+${component}\\s+from`),
      `MachineConfigView must import ${component}`,
    );
  }
  assert.match(viewText, /useMachineConfigStore/);
  // The view calls the store's loaders on mount so the compilers
  // and listings are populated by the time the panels render.
  assert.match(viewText, /loadAll\(\)/);
});

test("EditorView no longer imports machineconfig panels", () => {
  const viewText = readText(viewPath);
  // After the split, the editor view is editor-only. The machineconfig
  // surface lives at /machineconfig (MachineConfigView), so none of
  // its panels should leak into EditorView anymore.
  for (const component of [
    "ProfilesExplorer",
    "CompilerPanel",
    "CompiledOutputViewer",
    "DeploymentPanel",
    "ActivePanel",
    "MacroManagerPanel",
    "McodeManagerPanel",
  ]) {
    assert.doesNotMatch(
      viewText,
      new RegExp(`import\\s+${component}\\s+from`),
      `EditorView must not import ${component} any more`,
    );
  }
  assert.doesNotMatch(viewText, /useMachineConfigStore/);
});

test("EditorView closes non-gcode files by routing to machineconfig", () => {
  const viewText = readText(viewPath);
  // Closing the editor for a profile / cfg / mcode file must
  // bounce back to /machineconfig now that the legacy ``config``
  // route is editor-only.
  assert.match(
    viewText,
    /machineconfig/,
    "EditorView must reference machineconfig for the close-route target",
  );
  // gcode close still goes to programs.
  assert.match(viewText, /['"]programs['"]/);
});

test("App.vue reads the module mainView from the registry", () => {
  const appText = readText(resolve(repoRoot, "frontend/src/App.vue"));
  // App.vue looks up the registry record by the current route's
  // name and hands the ``mainView`` straight to ``<component>``.
  // The lazy ``import.meta.glob`` discovery and the
  // ``loadModuleView`` helper were retired with the no-lazy-imports
  // rule documented in ``.agent/STATE.md`` § 13.
  assert.match(
    appText,
    /registry\.modules\.get\(\s*name\s*\)/,
    "App.vue must look up the registry record by route name",
  );
  assert.match(
    appText,
    /record\?\.mainView/,
    "App.vue must read mainView off the registry record",
  );
  assert.doesNotMatch(
    appText,
    /\bloadModuleView\b/,
    "App.vue must not use a loadModuleView helper (lazy imports are banned)",
  );
  assert.match(
    appText,
    /<component\s+v-if="moduleView"\s+:is="moduleView"\s*\/>/,
    "App.vue still renders the resolved module view via <component :is>",
  );
});

test("AppSidebar no longer carries the legacy config built-in", () => {
  // The legacy ``id: 'config'`` built-in entry has been deleted;
  // machineconfig owns that sidebar slot under its own id.
  const sidebarText = readText(
    resolve(repoRoot, "frontend/src/components/AppSidebar.vue"),
  );
  assert.doesNotMatch(sidebarText, /id:\s*['"]config['"]/);
});