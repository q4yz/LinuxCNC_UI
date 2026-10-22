// No colour emojis in the UI: Raspberry Pi OS / Linux ships no emoji
// font, so 🏠 🔥 📂 … render as blank boxes on the machine's own screen.
// Use the shared SVG ``Icon`` (``src/ui/Icon.vue``) instead — add a
// path there when one is missing. Plain text symbols that the default
// Linux font (DejaVu) covers — ✓ ✕ ⚠ ▸ · → — are fine.
//
// Run with: ``node --test frontend/tests/test-no-emoji.ts``

import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = resolve(here, "../src");

// Pictographic emoji blocks + the emoji-presentation selector.
const EMOJI = /[\u{1F000}-\u{1FAFF}\u{2B00}-\u{2BFF}\u{FE0F}\u{274C}\u{2744}\u{2699}\u{23E9}-\u{23FA}]/u;

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sourceFiles(path);
    return /\.(vue|ts)$/.test(name) ? [path] : [];
  });
}

test("no colour emojis in UI source (use the SVG Icon)", () => {
  const offenders: string[] = [];
  for (const file of sourceFiles(src)) {
    readFileSync(file, "utf-8").split("\n").forEach((line, index) => {
      const code = line.trim();
      if (code.startsWith("//") || code.startsWith("*") || code.startsWith("<!--")) return;
      if (EMOJI.test(line)) offenders.push(`${relative(src, file)}:${index + 1}: ${code.slice(0, 80)}`);
    });
  }
  assert.deepEqual(offenders, [], `replace these with <Icon name="…" />:\n${offenders.join("\n")}`);
});

test("BaseCard takes an icon name instead of an emoji in the title", () => {
  const card = readFileSync(resolve(src, "ui/BaseCard.vue"), "utf-8");
  assert.match(card, /icon\?: string;/);
  assert.match(card, /<Icon v-if="icon" :name="icon" \/>/);
});
