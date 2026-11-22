// The facade boundary: only ``src/facades/`` talks to the backends.
// Components, stores, composables, helpers and views go through a facade,
// never the generated OpenAPI services, a raw ``fetch`` / ``WebSocket`` /
// ``EventSource`` or ``XMLHttpRequest`` (LESSONS_LEARNED.md § 2.7: a
// hand-rolled request breaks silently when the backend changes; the
// generated client, behind a facade, fails at compile time). Types from
// ``generated/api`` (models) may be imported anywhere.
//
// Every facade module exports one value named after its file
// (``ioFacade.ts`` -> ``export const ioFacade``) and default-exports it.
//
// Replaces test-no-hand-rolled-fetch.ts, which covered ``stores/`` only:
// the camera store, the macro button editor, the editor store, the
// machine-online composable and the thumbnail helper had slipped past it.
//
// Run with: ``node --test frontend/tests/test-facade-boundary.ts``

import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { basename, join, relative, resolve, dirname, sep } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = resolve(here, "../src");
const facadesDir = join(src, "facades");

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sourceFiles(path);
    return /\.(ts|vue)$/.test(name) ? [path] : [];
  });
}

const all = sourceFiles(src);
const outside = all.filter((p) => !p.startsWith(facadesDir + sep));
/** ``services/apiClient.ts`` configures the generated client (``OpenAPI.BASE``). */
const CLIENT_CONFIG = join(src, "services", "apiClient.ts");

/** Source without comments, so a mention in a comment is not a call. */
function code(path: string): string {
  return readFileSync(path, "utf-8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:"'`])\/\/.*$/gm, "$1")
    .replace(/<!--[\s\S]*?-->/g, "");
}

const rel = (p: string) => relative(src, p);

test("guard the guard: it sees the source tree", () => {
  assert.ok(outside.length > 50, `expected the app's sources, found ${outside.length}`);
  assert.ok(all.length > outside.length, "expected facades");
});

test("no generated service / request core outside facades/ (types are fine)", () => {
  const offenders: string[] = [];
  const importRe = /import\s+(type\s+)?([\s\S]*?)\s+from\s+["']([^"']*generated\/api[^"']*)["']/g;
  for (const path of outside) {
    if (path === CLIENT_CONFIG) continue;
    for (const m of code(path).matchAll(importRe)) {
      if (m[1]) continue; // import type { ... }
      const names = m[2].replace(/[{}]/g, "").split(",").map((n) => n.trim()).filter(Boolean)
        .filter((n) => !n.startsWith("type "));
      const runtime = names.filter((n) => /Service$|^(ApiError|OpenAPI|request|CancelablePromise)$/.test(n.split(/\s+as\s+/)[0]));
      if (runtime.length || /\/(services|core)\//.test(m[3])) offenders.push(`${rel(path)}: ${runtime.join(", ") || m[3]}`);
    }
  }
  assert.deepEqual(offenders, []);
});

test("no raw fetch / WebSocket / EventSource / XMLHttpRequest outside facades/", () => {
  const offenders = outside
    .filter((path) => /\bfetch\(|new WebSocket\(|new EventSource\(|XMLHttpRequest/.test(code(path)))
    .map(rel);
  assert.deepEqual(offenders, []);
});

test("every facade exports <file name> and default-exports it", () => {
  const facades = all.filter((p) => p.startsWith(facadesDir + sep) && p.endsWith(".ts"));
  assert.ok(facades.length >= 20, "expected the facades");
  const offenders = facades.filter((path) => {
    const name = basename(path, ".ts");
    const text = code(path);
    return !new RegExp(`^export const ${name}\\b`, "m").test(text) || !new RegExp(`^export default ${name};?$`, "m").test(text);
  });
  assert.deepEqual(offenders.map(rel), []);
});

test("no *Service classes in facades/ (the generated client owns that name)", () => {
  const offenders = all
    .filter((p) => p.startsWith(facadesDir + sep))
    .filter((path) => /^export class \w+Service\b/m.test(code(path)))
    .map(rel);
  assert.deepEqual(offenders, []);
});
