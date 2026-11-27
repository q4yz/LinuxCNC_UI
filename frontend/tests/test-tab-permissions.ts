// Config and Debug (and the HAL editor) are admin tabs: hidden from
// everyone else, and a typed URL goes back to the Dashboard.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = resolve(here, "../src");
const read = (p: string) => readFileSync(resolve(src, p), "utf-8");

test("the admin routes name their permission", () => {
  const router = read("router/index.ts");
  assert.match(router, /name: 'config'[^\n]*permission: 'config\.write'/);
  assert.match(router, /name: 'debug'[^\n]*permission: 'hal\.write'/);
  assert.match(router, /name: 'hal-editor'[^\n]*permission: 'hal\.write'/);
  assert.match(router, /installPermissionGuard\(router\)/);
});

test("the guard sends a login without the permission to the Dashboard", () => {
  const guard = read("router/guards/permissionGuard.ts");
  assert.match(guard, /return mayOpen\(permission\) \? true : \{ name: "dashboard" \}/);
  // unknown login (backend not answered yet): not shown, not opened
  assert.match(guard, /auth\.me !== null && auth\.can\(permission\)/);
});

test("the sidebar hides those tabs and leaves one on logout", () => {
  const sidebar = read("components/AppSidebar.vue");
  assert.match(sidebar, /\.filter\(\(item\) => mayOpen\(permissionOf\(item\.id\)\)\)/);
  assert.match(sidebar, /!mayOpen\(routePermission\(route\)\)\) void router\.replace\(\{ name: 'dashboard' \}\)/);
});
