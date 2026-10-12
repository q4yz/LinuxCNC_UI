// Profiles / Machines explorers: every row action lives in the shared
// "⋮" ActionMenu; folders with content can be deleted after a warning.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = (p: string) => resolve(here, "../src", p);
const read = (p: string) => readFileSync(src(p), "utf-8");

const { suggestCopyPath, folderContents } = await import(
  pathToFileURL(src("components/machineconfig/explorerActions.ts")).href
);
const { FileEntry } = await import(pathToFileURL(src("entities/files/FileEntry.ts")).href);

test("copy name suggestion keeps the extension and skips taken names", () => {
  assert.equal(suggestCopyPath("dir/printer.cfg", new Set()), "dir/printer-copy.cfg");
  assert.equal(suggestCopyPath("m1", new Set()), "m1-copy");
  assert.equal(suggestCopyPath("a.hal", new Set(["a-copy.hal", "a-copy-2.hal"])), "a-copy-3.hal");
  assert.equal(suggestCopyPath(".hidden", new Set()), ".hidden-copy");
});

test("folder contents count every depth, not siblings with the same prefix", () => {
  const entries = [
    new FileEntry({ name: "m1", path: "m1", kind: "folder" }),
    new FileEntry({ name: "configs", path: "m1/configs", kind: "folder", parent: "m1" }),
    new FileEntry({ name: "machine.hal", path: "m1/configs/machine.hal", parent: "m1/configs" }),
    new FileEntry({ name: "a.cfg", path: "m1/a.cfg", parent: "m1" }),
    new FileEntry({ name: "m10", path: "m10", kind: "folder" }),
    new FileEntry({ name: "x.cfg", path: "m10/x.cfg", parent: "m10" }),
  ];
  assert.deepEqual(folderContents("m1", entries), { files: 2, folders: 1 });
  assert.deepEqual(folderContents("m1/configs", entries), { files: 1, folders: 0 });
});

test("explorers put every action into the ⋮ menu", () => {
  for (const [file, store] of [
    ["components/machineconfig/ProfilesExplorer.vue", "Profile"],
    ["components/machineconfig/MachinesExplorer.vue", "Machine"],
  ]) {
    const text = read(file);
    assert.match(text, /<ActionMenu :items="menuItems\(entry\)"/, `${file}: one menu per row`);
    for (const key of ["edit", "download", "copy", "move", "delete"]) {
      assert.match(text, new RegExp(`key: "${key}"`), `${file}: menu offers ${key}`);
    }
    assert.match(text, new RegExp(`store\\.copy${store}\\(`), `${file}: copy is a real copy`);
    assert.match(text, /confirmDelete\(/, `${file}: delete asks first`);
    assert.match(text, new RegExp(`store\\.delete${store}\\(entry\\.path, recursive\\)`), `${file}: folder with content deletable`);
    assert.doesNotMatch(text, /title="Download"|aria-label="Start machine"|title="Open in Visual HAL Editor"/, `${file}: no inline action buttons left`);
    assert.doesNotMatch(text, /JSON\.stringify\(content/, `${file}: download writes the file, not "{}"`);
  }
  const machines = read("components/machineconfig/MachinesExplorer.vue");
  assert.match(machines, /key: "start"/);
  assert.match(machines, /key: "hal"/);
});

test("Generate and Set-as-default stay visible next to the ⋮ menu", () => {
  const profiles = read("components/machineconfig/ProfilesExplorer.vue");
  assert.doesNotMatch(profiles, /key: "generate"/, "Generate is not in the menu");
  assert.match(profiles, /v-if="isProfileCfg\(entry\)"[\s\S]{0,200}@click\.stop="onGenerate\(entry\)"[\s\S]{0,80}>Generate</);

  const machines = read("components/machineconfig/MachinesExplorer.vue");
  assert.doesNotMatch(machines, /key: "main"/, "Set as default is not in the menu");
  assert.match(machines, /@click\.stop="selectAsMain\(entry\)"[\s\S]{0,80}>Set as default</);
  assert.match(machines, /v-if="defaultMachine === entry\.name"/, "the default machine shows the main badge instead");
});

test("ActionMenu is teleported, closes on outside click / Escape / scroll", () => {
  const menu = read("ui/ActionMenu.vue");
  assert.match(menu, /<Teleport to="body">/);
  assert.match(menu, /"pointerdown", onOutside/);
  assert.match(menu, /event\.key === "Escape"/);
  assert.match(menu, /window\[method\]\("scroll", close, true\)/);
});
