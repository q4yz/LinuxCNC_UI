// Regression guard: no box-shadow anywhere in the frontend.
//
// Box-shadow (and drop-shadow) is expensive to rasterize/composite
// in software on GPU-less targets (e.g. a Raspberry Pi 4), and it
// was applied all over this dashboard — including on the shared
// ``BaseCard`` primitive used by nearly every panel, making it a
// whole-app cost rather than a one-off. Every shadow was removed in
// favour of borders; this test scans the whole ``frontend/src`` tree
// (Vue templates, scoped ``<style>`` CSS, and TS/JS class strings) so
// it fails loudly the moment one creeps back in, anywhere.
//
// Run with: ``node --test frontend/tests/test-no-shadow.ts``

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { resolve, dirname, join, extname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");
const srcDir = resolve(repoRoot, "frontend/src");

const SCAN_EXTENSIONS = new Set([".vue", ".ts", ".js", ".css"]);

// Matches any Tailwind shadow/drop-shadow utility (with scale
// suffixes or arbitrary values: shadow, shadow-md, shadow-2xl,
// shadow-[0_0_10px_red], drop-shadow-lg, ...) as well as the raw
// CSS ``box-shadow`` property.
const SHADOW_PATTERN = /\b(?:drop-)?shadow(?:-[\w[\]/.%#,]+)?\b|box-shadow\s*:/;

function collectFiles(dir: string, out: string[]): string[] {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    const stat = statSync(path);
    if (stat.isDirectory()) {
      collectFiles(path, out);
    } else if (SCAN_EXTENSIONS.has(extname(name))) {
      out.push(path);
    }
  }
  return out;
}

test("no shadow/box-shadow utility appears anywhere in frontend/src", () => {
  const files = collectFiles(srcDir, []);
  // Guard the guard: an empty scan means the walk is broken, not
  // that the codebase is clean.
  assert.ok(files.length > 0, "expected to find source files under frontend/src");

  const offenders: string[] = [];
  for (const path of files) {
    const text = readFileSync(path, "utf-8");
    if (SHADOW_PATTERN.test(text)) {
      offenders.push(path.slice(repoRoot.length + 1).replace(/\\/g, "/"));
    }
  }

  assert.deepEqual(
    offenders,
    [],
    `shadow/box-shadow found in: ${offenders.join(", ")} — box-shadow compositing is ` +
      "expensive on GPU-less targets (e.g. Raspberry Pi 4); use a border instead.",
  );
});
