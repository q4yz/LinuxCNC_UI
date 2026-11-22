// Every panel card is a BaseCard: its header (title + #header-actions)
// is what moves clear of the fixed E-stop box (ui/estopClearance.ts) when
// the card sits under it. A hand-built card or header row does not
// move, and its buttons end up under the E-stop (the Machines explorer,
// the raw machine state, the HAL pins panel, the G-code files did).
//
// Run with: ``node --test frontend/tests/test-card-architecture.ts``

import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = resolve(here, "../src");

function vueFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return vueFiles(path);
    return name.endsWith(".vue") ? [path] : [];
  });
}

const files = vueFiles(src).filter((path) => !path.endsWith(join("ui", "BaseCard.vue")));

/** Class lists in a template (static ``class="..."``). */
function classLists(text: string): string[] {
  return [...text.matchAll(/\sclass="([^"]*)"/g)].map((m) => m[1]);
}

const has = (list: string, ...tokens: string[]) => tokens.every((t) => list.split(/\s+/).includes(t));

test("no hand-built card header (BaseCard's title / #header-actions instead)", () => {
  const offenders = files.filter((path) =>
    classLists(readFileSync(path, "utf-8")).some((list) => has(list, "bg-gray-700/50", "border-b", "border-gray-600")),
  );
  assert.deepEqual(offenders.map((p) => relative(src, p)), []);
});

test("no hand-built panel card (rounded-lg border-gray-700 bg-gray-800 box)", () => {
  // Modals / menus use border-gray-600 or a translucent bg: not panels.
  const offenders = files.filter((path) =>
    classLists(readFileSync(path, "utf-8")).some((list) =>
      has(list, "rounded-lg", "border", "border-gray-700", "bg-gray-800") && !/\bfixed\b|\babsolute\b/.test(list),
    ),
  );
  assert.deepEqual(offenders.map((p) => relative(src, p)), []);
});

test("the cards that used to be hand-built are BaseCards with a title", () => {
  for (const [file, title] of [
    ["components/machineconfig/MachinesExplorer.vue", 'title="Machines"'],
    ["components/machineconfig/ProfilesExplorer.vue", 'title="Profiles"'],
    ["components/FileManager.vue", 'title="G-Code Files"'],
    ["components/DebugPanel.vue", 'title="Raw Machine State (3s Snapshot)"'],
    ["components/debug/HalPinStatePanel.vue", 'title="HAL pins"'],
  ]) {
    const text = readFileSync(join(src, file), "utf-8");
    assert.ok(text.includes(`<BaseCard ${title}`), `${file}: <BaseCard ${title}`);
  }
});
