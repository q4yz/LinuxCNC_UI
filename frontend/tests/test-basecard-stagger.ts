// Structural guard for BaseCard's staggered-mount behavior.
//
// Nearly every dashboard panel wraps itself in BaseCard, and several
// (the WebGL viewer's card, the ECharts temperature chart, the file
// lists) are expensive to construct. They're all gated behind the
// same MachineGate ref, so going online used to flip every one of
// those v-if branches — and therefore mount every heavy child — in
// one synchronous render pass. BaseCard now reveals its own default
// slot after a small random delay so that one long blocking task
// becomes several short ones instead. See the comment in
// ui/BaseCard.vue for the full reasoning (why a random draw instead
// of a shared round-robin queue, why 15ms).
//
// Run with: ``node --test frontend/tests/test-basecard-stagger.ts``

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");
const baseCardPath = resolve(repoRoot, "frontend/src/ui/BaseCard.vue");

function read(): string {
  return readFileSync(baseCardPath, "utf-8");
}

test("BaseCard defers its default slot behind a random-delay reveal", () => {
  const text = read();
  assert.match(text, /const ready = ref\(!props\.stagger\)/, "must start unrevealed unless stagger is opted out");
  assert.match(text, /<slot v-if="ready"\s*\/>/, "default slot must be gated on the reveal flag");
  assert.match(
    text,
    /Math\.random\(\)\s*\*\s*STAGGER_MAX_MS/,
    "the reveal delay must be a continuous random draw, not a fixed/shared schedule",
  );
  assert.match(text, /STAGGER_MAX_MS\s*=\s*15/, "max stagger must be 15ms");
});

test("BaseCard supports opting a card out of staggering entirely", () => {
  const text = read();
  // A card whose slot is just a placeholder/Teleport target (e.g.
  // DashboardView's "Toolpath" card — see test-machine-online.ts)
  // has no heavy work to defer, and staggering it can break code
  // elsewhere that assumes the placeholder exists synchronously
  // right after mount. ``stagger: false`` must skip the timer
  // entirely, not just resolve it immediately, so ``ready`` is true
  // on the very first render — not one microtask/macrotask later.
  assert.match(text, /stagger\?:\s*boolean/, "must expose a stagger prop");
  assert.match(text, /stagger:\s*true/, "must default to staggering on (the common case)");
  assert.match(
    text,
    /if\s*\(!props\.stagger\)\s*return;/,
    "onMounted must skip scheduling the reveal timer when stagger is false",
  );
});

test("BaseCard shows a placeholder skeleton before the reveal", () => {
  const text = read();
  assert.match(
    text,
    /<slot v-if="ready"\s*\/>\s*<div v-else[^>]*class="[^"]*animate-pulse/,
    "the unrevealed state must render a lightweight skeleton, not a blank gap",
  );
});

test("BaseCard cleans up its reveal timer on unmount", () => {
  const text = read();
  assert.match(text, /onBeforeUnmount\(/, "must clear the pending timer if unmounted before it fires");
  assert.match(text, /clearTimeout\(revealTimer\)/, "must clear the specific reveal timer handle");
});

test("BaseCard's footer region renders for footer-actions content, not just footer text", () => {
  const text = read();
  // ConsolePanel (and any future consumer) needs to put non-text
  // content (an input bar, buttons) in the footer without being
  // forced to also supply a meaningless ``footer`` label string.
  assert.match(
    text,
    /v-if="footer \|\| \$slots\['footer-actions'\]"/,
    "footer region must render when either footer text or the footer-actions slot has content",
  );
});

// ------------------------------------------------------------------ //
// content-visibility: skip layout/paint for off-screen cards            //
// ------------------------------------------------------------------ //
//
// The Dashboard stacks 7+ cards in one scrollable column; without a
// containment boundary, scrolling past them can force the browser to
// redo layout/paint for the whole stack on every frame — expensive
// in software rendering (no GPU) on a Pi 4. content-visibility: auto
// only imposes containment while a card is off-screen, so a fully
// visible card (including a modal, always visible when shown) is
// completely unaffected — safe to default on for every consumer.

test("BaseCard applies content-visibility with a per-card size estimate", () => {
  const text = read();
  assert.match(text, /minHeight\?:\s*number/, "must expose a minHeight override prop");
  assert.match(text, /minHeight:\s*220/, "must default to a reasonable estimate for typical panels");
  assert.match(
    text,
    /contentVisibility:\s*'auto'/,
    "must turn on content-visibility so off-screen cards skip layout/paint",
  );
  assert.match(
    text,
    /containIntrinsicSize:\s*`auto \$\{props\.minHeight\}px`/,
    "must use the auto keyword so the real measured size is remembered after first render, not just the estimate forever",
  );
  assert.match(text, /:style="cardStyle"/, "the root element must actually apply the computed style");
});
