// Every file selector uses the shared ``ui/FileDropZone.vue`` (drag &
// drop + a multi-file picker), and every file listing is mapped to the
// one ``FileEntry`` entity from the backend's shared
// ``FileEntryResponse``.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = resolve(here, "../src");
const read = (rel: string) => readFileSync(resolve(src, rel), "utf-8");

const SELECTORS = [
  "components/FileManager.vue",
  "components/machineconfig/ProfilesExplorer.vue",
  "components/machineconfig/MachinesExplorer.vue",
];

test("FileDropZone: multi-file picker + drop, counted drag depth, file drags only", () => {
  const text = read("ui/FileDropZone.vue");
  assert.match(text, /type="file"/, "hidden input for the picker");
  assert.match(text, /:multiple="multiple"/, "picker honours multiple");
  assert.match(text, /multiple: true/, "multiple is the default");
  assert.match(text, /dragDepth\+\+/, "enter/leave are counted so child elements do not flicker the overlay");
  assert.match(text, /includes\("Files"\)/, "only drags that carry files are handled");
  assert.match(text, /defineExpose\(\{ openPicker \}\)/, "consumers can open the picker");
  assert.match(text, /el\.value = ""/, "the input resets so the same file can be picked twice");
});

for (const rel of SELECTORS) {
  test(`${rel} uses the shared FileDropZone`, () => {
    const text = read(rel);
    assert.match(text, /<FileDropZone/, "wrapped in FileDropZone");
    assert.match(text, /@files="uploadFiles"/, "drop + picker share one upload handler");
    assert.match(text, /openPicker/, "an Upload button opens the picker");
    assert.doesNotMatch(text, /dataTransfer/, "no hand-rolled drop handling");
    assert.doesNotMatch(text, /type="file"/, "no own file input");
  });
}

test("file lists use the FileEntry entity, not raw wire shapes", () => {
  for (const rel of [...SELECTORS, "components/ActivePrintWidget.vue"]) {
    const text = read(rel);
    assert.match(text, /FileEntry/, `${rel} must use FileEntry`);
    assert.doesNotMatch(text, /DirectoryEntryModel|FileInfo\b|size_bytes/, `${rel} must not use wire shapes`);
  }
});

test("toFileEntry maps the shared FileEntryResponse", async () => {
  const { toFileEntry, toFileListing } = await import(pathToFileURL(resolve(src, "mappers/filesMapper.ts")).href);
  const entry = toFileEntry({
    name: "part.ngc",
    path: "jobs/part.ngc",
    parent: "jobs",
    kind: "file",
    size_bytes: 42,
    modified: "2026-10-09T12:00:00",
    read_only: true,
    has_marker: true,
  });
  assert.equal(entry.name, "part.ngc");
  assert.equal(entry.path, "jobs/part.ngc");
  assert.equal(entry.parent, "jobs");
  assert.equal(entry.isFile, true);
  assert.equal(entry.sizeBytes, 42);
  assert.equal(entry.modified, "2026-10-09T12:00:00");
  assert.equal(entry.modifiedMs, Date.parse("2026-10-09T12:00:00"));
  assert.equal(entry.readOnly, true);
  assert.equal(entry.hasMarker, true);

  assert.deepEqual(toFileListing([{ name: "", path: "", kind: "file" }]), [], "nameless rows are dropped");
  const folder = toFileEntry({ name: "jobs", path: "jobs", kind: "folder" });
  assert.equal(folder.isFolder, true);
  assert.equal(folder.modified, null);
  assert.equal(folder.modifiedMs, 0);
});

test("formatFileSize / formatFileDate are shared", async () => {
  const { formatFileSize, formatFileDate } = await import(pathToFileURL(resolve(src, "helpers/fileFormat.ts")).href);
  assert.equal(formatFileSize(0), "0 B");
  assert.equal(formatFileSize(512), "512 B");
  assert.equal(formatFileSize(2048), "2.0 KB");
  assert.equal(formatFileSize(3 * 1024 * 1024), "3.0 MB");
  assert.equal(formatFileDate(null), "—");
  assert.equal(formatFileDate("not a date"), "—");
  assert.notEqual(formatFileDate("2026-10-09T12:00:00"), "—");
});
