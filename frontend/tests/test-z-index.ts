// The E-stop box is always on top: it has the highest z-index of the whole
// frontend, and it alone. Every other z-index — Tailwind ``z-<n>`` /
// ``z-[<n>]``, ``z-index: <n>`` in CSS, ``zIndex: <n>`` in a style binding —
// must be smaller. A computed z-index (no number to check) is only allowed
// where it cannot compete: inside a layer that has a fixed, smaller one
// (the floating windows inside their z-30 layer).
//
// Run with: ``node --test frontend/tests/test-z-index.ts``

import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const src = join(root, "src");

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return files(path);
    return /\.(vue|ts|js|css)$/.test(name) ? [path] : [];
  });
}

interface Use {
  file: string;
  line: number;
  text: string;
  value: number | null; // null: computed, not a number
}

// Tailwind (also with a variant prefix, md:z-10 / !z-10), CSS, style bindings.
const TAILWIND = /(?:^|[\s"'`:!])-?z-(\[(-?\d+)\]|(\d+))(?![\w-])/g;
const CSS = /z-index\s*:\s*([^;}"'\n]+)/g;
const BINDING = /zIndex\s*:\s*([^,}\n]+)/g;

function uses(): Use[] {
  const out: Use[] = [];
  for (const path of [...files(src), join(root, "index.html")]) {
    const file = relative(root, path);
    readFileSync(path, "utf-8").split("\n").forEach((text, k) => {
      for (const m of text.matchAll(TAILWIND)) {
        out.push({ file, line: k + 1, text: m[0].trim(), value: Number(m[2] ?? m[3]) });
      }
      for (const m of [...text.matchAll(CSS), ...text.matchAll(BINDING)]) {
        const raw = m[1].trim();
        out.push({ file, line: k + 1, text: m[0].trim(), value: /^-?\d+$/.test(raw) ? Number(raw) : null });
      }
    });
  }
  return out;
}

const all = uses();
const ESTOP_FILE = "src/components/EStopHeader.vue";
const estop = all.find((u) => u.file === ESTOP_FILE && u.value !== null);

test("the E-stop box has a fixed z-index", () => {
  assert.ok(estop, "EStopHeader.vue must set a z-index");
  assert.match(readFileSync(join(root, ESTOP_FILE), "utf-8"), /data-estop-overlay class="fixed top-0 right-0 z-\[100\]/);
});

test("every other z-index is smaller than the E-stop box's: it alone is the highest", () => {
  const max = estop!.value!;
  const offenders = all
    .filter((u) => u !== estop && u.value !== null && u.value >= max)
    .map((u) => `${u.file}:${u.line} ${u.text}`);
  assert.deepEqual(offenders, [], `z-index ${max} (the E-stop box) or higher elsewhere`);
});

test("a computed z-index only inside a layer with a fixed, smaller one", () => {
  // file -> the fixed layer z-index its computed ones live in
  const CONTAINED: Record<string, RegExp> = {
    "src/components/FloatingPanelHost.vue": /class="pointer-events-none fixed inset-0 z-30" data-testid="floating-panel-layer"/,
  };
  const computed = all.filter((u) => u.value === null);
  for (const u of computed) {
    const layer = CONTAINED[u.file];
    assert.ok(layer, `${u.file}:${u.line} ${u.text}: a computed z-index could end up over the E-stop box`);
    assert.match(readFileSync(join(root, u.file), "utf-8"), layer, `${u.file}: its layer must stay`);
  }
});

test("the scan finds the known layers (it is not silently empty)", () => {
  const found = (file: string, value: number) => all.some((u) => u.file === file && u.value === value);
  assert.ok(found("src/App.vue", 40), "the sidebar z-40");
  assert.ok(found("src/components/ToastContainer.vue", 90), "the toasts z-[90]");
  assert.ok(found("src/components/FloatingPanelHost.vue", 30), "the window layer z-30");
});
