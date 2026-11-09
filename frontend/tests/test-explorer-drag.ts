// Drag & drop in the explorers (G-code files, Machines, Profiles) and the
// sortable G-code files table.
//
// Run with: ``node --test frontend/tests/test-explorer-drag.ts``

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import { ENTRY_DRAG_TYPE, dropDestination, sortEntries } from "../src/components/machineconfig/entryDrag";

const src = resolve(dirname(fileURLToPath(import.meta.url)), "../src");
const read = (rel: string) => readFileSync(resolve(src, rel), "utf-8");

test("a drop moves into the folder, never into itself or where it already is", () => {
  assert.equal(dropDestination("part.ngc", "jobs"), "jobs/part.ngc");
  assert.equal(dropDestination("jobs/part.ngc", ""), "part.ngc", "breadcrumb root: out of the folder");
  assert.equal(dropDestination("a/b/part.ngc", "a"), "a/part.ngc", "one level up");
  assert.equal(dropDestination("jobs/part.ngc", "jobs"), null, "same folder");
  assert.equal(dropDestination("jobs", "jobs"), null, "onto itself");
  assert.equal(dropDestination("jobs", "jobs/sub"), null, "into its own subfolder");
  assert.equal(dropDestination("jobs", "jobsX"), "jobsX/jobs", "a sibling with a similar name is fine");
  assert.notEqual(ENTRY_DRAG_TYPE, "Files", "uploads (FileDropZone) never see an internal drag");
});

test("sorting: folders first, then by the column, both directions", () => {
  const rows = [
    { name: "b.ngc", isFolder: false, sizeBytes: 300, modifiedMs: 1 },
    { name: "a.ngc", isFolder: false, sizeBytes: 100, modifiedMs: 3 },
    { name: "zeta", isFolder: true, modifiedMs: 2 },
    { name: "alpha", isFolder: true, modifiedMs: 5 },
  ];
  const names = (key: "name" | "size" | "date", dir: "asc" | "desc") =>
    sortEntries(rows, key, dir, (f) => (f.name === "zeta" ? 9 : 1)).map((r) => r.name);
  assert.deepEqual(names("name", "asc"), ["alpha", "zeta", "a.ngc", "b.ngc"]);
  assert.deepEqual(names("name", "desc"), ["zeta", "alpha", "b.ngc", "a.ngc"]);
  assert.deepEqual(names("size", "desc"), ["zeta", "alpha", "b.ngc", "a.ngc"], "folder size = child count");
  assert.deepEqual(names("date", "desc"), ["alpha", "zeta", "a.ngc", "b.ngc"]);
});

test("the G-code table sorts by each column and drags rows", () => {
  const view = read("components/FileManager.vue");
  for (const key of ["name", "size", "date"]) assert.match(view, new RegExp(`@click="sortBy\\('${key}'\\)"`));
  assert.match(view, /sortEntries\(files\.value\.filter\(inCurrent\), sortKey\.value, sortDir\.value, childCount\)/);
  assert.match(view, /draggable="true"[\s\S]*?@dragstart="drag\.onDragStart\(folder\.path, \$event\)"[\s\S]*?@drop="drag\.onDrop\(folder\.path, \$event\)"/);
  assert.match(view, /@dragstart="drag\.onDragStart\(file\.path, \$event\)"/);
  assert.match(view, /@drop="drag\.onDrop\('', \$event\)"/, "breadcrumb root takes a drop");
  assert.match(view, /<DragBin[\s\S]*?@drop="drag\.onBinDrop"/);
});

for (const [file, rename] of [
  ["components/machineconfig/ProfilesExplorer.vue", "renameProfile"],
  ["components/machineconfig/MachinesExplorer.vue", "renameMachine"],
] as const) {
  test(`${file}: drag onto folders / breadcrumbs moves, the bin deletes`, () => {
    const view = read(file);
    assert.match(view, new RegExp(`store\\.${rename}\\(source, destination\\)`));
    assert.match(view, /draggable="true"[\s\S]*?@dragstart="drag\.onDragStart\(entry\.path, \$event\)"/);
    assert.match(view, /@drop="entry\.kind === 'folder' && drag\.onDrop\(entry\.path, \$event\)"/);
    assert.match(view, /@drop="drag\.onDrop\('', \$event\)"/);
    assert.match(view, /<DragBin[\s\S]*?@drop="drag\.onBinDrop"/);
    assert.match(view, /remove: async \(path\)[\s\S]*?await deleteEntry\(entry\)/, "the bin asks like the ⋮ menu");
  });
}

test("the main machine is not moved by a drag", () => {
  assert.match(read("components/machineconfig/MachinesExplorer.vue"), /holds the main machine — select another main machine before moving it/);
});
