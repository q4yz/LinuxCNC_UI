// Static-structure tests for the registry-driven Vue Router contract.
//
// Run with: node --test frontend/tests/test-router-modules.mjs
//
// ``router/index.js::registerModuleRoutes`` adds one ``/<sidebarId>``
// route per mounted module whose manifest declares a sidebar entry.
// These source-text checks pin the contract that makes the camera
// sidebar entry (and any future module's entry) navigable:
//
//   * ``registerModuleRoutes`` walks ``registry.modules`` and adds the
//     route via Vue Router's ``addRoute``;
//   * each added route carries the module's sidebar id as its
//     ``name``;
//   * built-in route names (``dashboard``, ``programs``, ``config``,
//     ``settings``) win over a colliding module;
//   * ``main.js`` awaits ``registry.boot()`` and then calls
//     ``registerModuleRoutes(registry)`` BEFORE mounting the app so
//     the initial navigation resolves.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");

const routerPath = resolve(repoRoot, "frontend/src/router/index.ts");
const mainPath = resolve(repoRoot, "frontend/src/main.ts");
const registryPath = resolve(repoRoot, "frontend/src/core/modules/registry.ts");

function read(p) {
  return readFileSync(p, "utf-8");
}

test("router/index.js exports registerModuleRoutes", () => {
  const text = read(routerPath);
  assert.match(
    text,
    /export\s+function\s+registerModuleRoutes\s*\(/,
    "router/index.js must export registerModuleRoutes()",
  );
});

test("registerModuleRoutes walks the mounted registry and addRoute's per sidebar entry", () => {
  const text = read(routerPath);
  // Walks the registry's reactive Map.
  assert.match(
    text,
    /registry\.modules\.\w+\(\)/,
    "registerModuleRoutes must iterate registry.modules",
  );
  // Each entry adds a route via the canonical Vue Router API.
  assert.match(
    text,
    /router\.addRoute\s*\(/,
    "registerModuleRoutes must call router.addRoute() per sidebar entry",
  );
  // The route's path is ``/<sidebarId>`` so a click on the camera
  // sidebar entry lands at ``/camera``.
  assert.match(
    text,
    /path:\s*[`'"]\/\$\{[^}]*\.id\}['"`]/,
    "each added route's path must be '/' + sidebar.id",
  );
  // The route's name matches the sidebar id so AppSidebar's
    // ``router.push({ name: item.id })`` finds the route.
  assert.match(
    text,
    /name:\s*sidebar\.id/,
    "the added route's name must equal sidebar.id",
  );
});

test("registerModuleRoutes skips built-in route names", () => {
  // Built-in collision protection: if a module's manifest declared
  // ``sidebar.id === 'programs'`` for any reason, the built-in
  // dashboard/programs/editor/settings surface wins over the dynamic
  // override. The built-in names must be read off the static
  // route table. Issue #132 renamed the editor route from
  // ``config`` to ``editor``; the built-in list must reflect that.
  const text = read(routerPath);
  assert.match(
    text,
    /builtInNames\s*[=:]/,
    "must keep a Set of built-in route names to defend against collisions",
  );
  for (const name of ["dashboard", "programs", "editor", "settings"]) {
    assert.match(
      text,
      new RegExp(`['"\`]${name}['"\`]`),
      `built-in name list must contain ${name}`,
    );
  }
});

test("registerModuleRoutes is awaited after boot in main.js", () => {
  const text = read(mainPath);
  // The route table must be populated BEFORE the app mounts —
  // otherwise the first navigation fires before /camera is known.
  assert.match(text, /registerModuleRoutes\s*\(/);
  // Imports both the router (default export) and the helper.
  assert.match(
    text,
    /import\s+(?:router\s*,\s*)?\{\s*registerModuleRoutes\s*\}\s+from\s+["']\.\/router["']/,
    "main.js must destructure registerModuleRoutes from ./router",
  );
  // Order: boot().then(register).finally(mount).
  assert.match(text, /registry\.boot\(\)/);
  // The mount must happen after registration, not before.
  const bootIdx = text.indexOf("registry.boot(");
  const registerIdx = text.indexOf("registerModuleRoutes(");
  const mountIdx = text.indexOf("app.mount(");
  assert.ok(
    bootIdx >= 0 && registerIdx > bootIdx && mountIdx > registerIdx,
    "main.js must order: boot → register → mount",
  );
});

test("Registry _mount records the module's mainView (with markRaw)", () => {
  const text = read(registryPath);
  // The contract relied on by App.vue's ``moduleView`` computed —
  // every mounted record must carry the module's ``mainView``
  // wrapped in ``markRaw`` so Vue does not warn about reactive
  // components when the registry stores them in its reactive Map.
  assert.match(
    text,
    /mainView:\s*markRaw\s*\(\s*instance\.mainView\s*\)/,
    "registry._mount must include mainView from instance.mainView",
  );
});
