// Uploads convert in the background: the file list shows them as
// converting (no Load, no preview, no thumbnail), refreshes itself, and
// reports when they are ready or failed.
//
// Run with: ``node --test frontend/tests/test-background-conversion-ui.ts``

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { toFileEntry } from "../src/mappers/filesMapper";

const src = resolve(dirname(fileURLToPath(import.meta.url)), "../src");
const read = (rel: string) => readFileSync(resolve(src, rel), "utf-8");

test("the entry carries the conversion status", () => {
  const converting = toFileEntry({ name: "a.ngc", path: "a.ngc", kind: "file", status: "converting" } as never)!;
  assert.equal(converting.status, "converting");
  const failed = toFileEntry({ name: "b.ngc", path: "b.ngc", kind: "file", status: "failed", message: "bad" } as never)!;
  assert.equal(failed.status, "failed");
  assert.equal(failed.message, "bad");
  assert.equal(toFileEntry({ name: "c.ngc", path: "c.ngc", kind: "file" } as never)!.status, null);
});

test("the list shows it, blocks Load / preview / thumbnail, and polls until done", () => {
  const view = read("components/FileManager.vue");
  assert.match(view, /:data-test="`file-converting-\$\{file\.path\}`"/);
  assert.match(view, /:data-test="`file-failed-\$\{file\.path\}`"/);
  assert.match(view, /:disabled="!isMachineOnline \|\| busyFile !== null \|\| file\.status !== null"/);
  assert.match(view, /@click="!file\.status && openPreview\(file\)"/);
  assert.match(view, /if \(!file\.status\) void ensure\(file\.path\)/);
  assert.match(view, /files\.value\.some\(\(f\) => f\.status === 'converting'\)\s*\? setTimeout\(fetchFiles, CONVERSION_POLL_MS\)/);
  assert.match(view, /consoleStore\.success\(`Converted \$\{file\.path\} — ready to load`\)/);
});
