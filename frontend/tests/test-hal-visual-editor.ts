// Structural guard for the Visual HAL Editor's "real data in, nothing
// out" contract.
//
// The editor is a live, READ-ONLY view over the real HAL world:
// pins/signals come from `GET /api/v1/hal/layout` via
// `facades/halFacade.ts` (adapted in `views/hal-visual-editor/loadHalData.ts`),
// existing signals are seeded onto the canvas as pre-wired pin nodes,
// and NOTHING ever writes back to the backend — in-session edits are
// frontend state, Refresh re-fetches and resets to backend truth.
//
// Run with: ``node --test frontend/tests/test-hal-visual-editor.ts``

import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");
const src = resolve(repoRoot, "frontend/src");
const editorDir = resolve(src, "views/hal-visual-editor");

const read = (rel) => readFileSync(resolve(src, rel), "utf-8");
const readEditor = (name) => readFileSync(resolve(editorDir, name), "utf-8");

// ------------------------------------------------------------------ //
// Mock era is gone                                                       //
// ------------------------------------------------------------------ //

test("mock pin palette is deleted; the editor uses the real HalPin type", () => {
  assert.ok(
    !existsSync(resolve(editorDir, "mockPins.ts")),
    "views/hal-visual-editor/mockPins.ts must be deleted",
  );
  const types = readEditor("types.ts");
  assert.match(types, /export interface HalPin\b/, "the real pin type must be named HalPin");
  assert.ok(!/\bMockPin\b/.test(types), "no MockPin may remain in types.ts");
  assert.match(types, /componentName\?/, "HalPin carries the owning component");
  // Seeded wires carry the backend signal's name.
  assert.match(types, /label\?: string/, "Wire must support an optional signal-name label");
});

// ------------------------------------------------------------------ //
// Read-only guarantee                                                    //
// ------------------------------------------------------------------ //

test("the editor never talks to the backend except through the read-only facade", () => {
  // Every file in the editor folder: no hand-rolled fetch, no
  // generated client, no HTTP verbs — the ONLY network path is the
  // facade's fetchLayout().
  for (const name of readdirSync(editorDir)) {
    const text = readEditor(name);
    assert.ok(
      !/\bfetch\s*\(/.test(text),
      `${name} must not call fetch() directly`,
    );
    assert.ok(
      !/\b(post|put|patch|delete)\s*\(/i.test(text.replace(/remove|drop/g, "")),
      `${name} must not perform HTTP writes`,
    );
    assert.ok(
      !/"\/api\//.test(text) && !/'\/api\//.test(text),
      `${name} must not hand-roll API URLs`,
    );
  }

  // The facade stays read-only: exactly one exported network method.
  const facade = read("facades/halFacade.ts");
  assert.match(facade, /fetchLayout/, "facade must expose fetchLayout()");
  for (const verb of ["post", "put", "patch", "delete"]) {
    assert.ok(
      !new RegExp(`\\.${verb}\\b`, "i").test(facade.replace(/deleted|drops/g, "")),
      `facade must not issue HTTP ${verb.toUpperCase()}`,
    );
  }
});

// ------------------------------------------------------------------ //
// Loader / adapter                                                       //
// ------------------------------------------------------------------ //

test("loadHalData adapts the real backend resources", () => {
  const text = readEditor("loadHalData.ts");
  assert.match(
    text,
    /HalVisualService\.fetchLayout\(\)/,
    "loader must go through the read-only facade",
  );
  assert.match(text, /full_name/, "adapter maps HalPinResource.full_name");
  assert.match(text, /VALID_TYPES/, "unknown type tokens must be filtered out");
  assert.match(text, /interface SeedSignal/, "signals must be prepared for seeding");
  assert.match(text, /null/, "adapter may drop un-mappable rows (null contract)");
});

// ------------------------------------------------------------------ //
// Canvas engine                                                          //
// ------------------------------------------------------------------ //

test("useHalCanvas injects real pins and seeds backend signals", () => {
  const text = readEditor("useHalCanvas.ts");
  assert.ok(!/mockPins/i.test(text), "canvas must not reference the deleted mock palette");
  assert.match(text, /function setPins\(/, "palette must be injectable (setPins)");
  assert.match(text, /function seedSignals\(/, "canvas must seed existing backend signals");
  assert.match(text, /function reset\(/, "canvas must support reset-to-backend-truth");
  assert.match(
    text,
    /connectWire\(fromPortId: string, toPortId: string, label\?: string\)/,
    "connectWire must carry the seeded signal-name label",
  );
});

// ------------------------------------------------------------------ //
// View wiring                                                            //
// ------------------------------------------------------------------ //

test("VisualHalEditor loads real data, is machine-gated, and offers Refresh", () => {
  const text = read("views/VisualHalEditor.vue");

  assert.match(text, /MachineGate/, "editor must be wrapped in MachineGate (HAL is :8000 data)");
  assert.match(text, /loadHalLayout\(\)/, "view must load through the adapter");
  assert.match(text, /canvas\.setPins\(/, "loaded pins must be injected into the canvas");
  assert.match(text, /canvas\.seedSignals\(/, "loaded signals must be seeded onto the canvas");
  assert.match(text, /canvas\.reset\(\)/, "refresh must reset the canvas before re-seeding");
  assert.match(
    text,
    /watch\(isMachineOnline/,
    "editor must re-fetch when the machine comes back online",
  );

  assert.match(text, /data-test="hal-refresh"/, "Refresh control must exist");
  assert.match(text, /data-test="hal-counts"/, "pin/signal counts must be shown");
  assert.match(text, /data-test="hal-load-error"/, "fetch failures must surface with a retry");

  // Real machines have hundreds of pins — both drawers filter.
  assert.match(text, /data-test="hal-input-search"/, "input drawer search");
  assert.match(text, /data-test="hal-output-search"/, "output drawer search");
});

// ------------------------------------------------------------------ //
// Dead code removal                                                      //
// ------------------------------------------------------------------ //

test("the old three-column halVisual store and its test are deleted", () => {
  assert.ok(
    !existsSync(resolve(src, "stores/halVisual.ts")),
    "stores/halVisual.ts must be deleted (no view imported it)",
  );
  assert.ok(
    !existsSync(resolve(repoRoot, "frontend/tests/test-hal-visual-store.ts")),
    "the old store's test must be deleted with it",
  );
  // The facade survives — it is the editor's read-only network path.
  assert.ok(existsSync(resolve(src, "facades/halFacade.ts")), "facades/halFacade.ts must stay");
});
