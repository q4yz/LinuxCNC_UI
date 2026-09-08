// Structural guard for the Visual HAL Editor's "file-scoped, editable,
// saves through the facade" contract.
//
// The editor is opened for one specific `.hal` file (via the `file`
// route query param, set by the button in `MachinesExplorer.vue`).
// Pins (live HAL introspection) and that file's signals come from
// `GET /api/v1/hal/layout?file=...` via `facades/halFacade.ts`
// (adapted in `views/hal-visual-editor/loadHalData.ts`); saving goes
// through the same facade's `saveLayout()`, the only write path — no
// component hand-rolls fetch/HTTP verbs/API URLs directly.
//
// Run with: ``node --test frontend/tests/test-hal-visual-editor.ts``

import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");
const src = resolve(repoRoot, "frontend/src");
const editorDir = resolve(src, "views/hal-visual-editor");
const generatedPath = resolve(repoRoot, "frontend/generated/api/index.ts");

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
// All network access goes through the facade                            //
// ------------------------------------------------------------------ //

test("the editor never talks to the backend except through the facade", () => {
  // Every file in the editor folder: no hand-rolled fetch, no
  // generated client, no hand-rolled API URLs — the ONLY network path
  // is the facade's fetchLayout()/saveLayout().
  for (const name of readdirSync(editorDir)) {
    const text = readEditor(name);
    assert.ok(
      !/\bfetch\s*\(/.test(text),
      `${name} must not call fetch() directly`,
    );
    assert.ok(
      !/"\/api\//.test(text) && !/'\/api\//.test(text),
      `${name} must not hand-roll API URLs`,
    );
  }

  // The facade exposes exactly the read + the file-scoped write.
  const facade = read("facades/halFacade.ts");
  assert.match(facade, /fetchLayout/, "facade must expose fetchLayout()");
  assert.match(facade, /saveLayout/, "facade must expose saveLayout()");
  for (const verb of ["post", "patch", "delete"]) {
    assert.ok(
      !new RegExp(`\\.${verb}\\b`, "i").test(facade),
      `facade must not issue HTTP ${verb.toUpperCase()}`,
    );
  }
});

// ------------------------------------------------------------------ //
// Loader / adapter                                                       //
// ------------------------------------------------------------------ //

test("loadHalData adapts the real backend resources for a specific file", () => {
  const text = readEditor("loadHalData.ts");
  assert.match(
    text,
    /HalVisualService\.fetchLayout\(file\)/,
    "loader must pass the target file through to the facade",
  );
  assert.match(text, /full_name/, "adapter maps HalPinResource.full_name");
  assert.match(text, /VALID_TYPES/, "unknown type tokens must be filtered out");
  assert.match(text, /interface SeedSignal/, "signals must be prepared for seeding");
  assert.match(text, /null/, "adapter may drop un-mappable rows (null contract)");
});

// ------------------------------------------------------------------ //
// Canvas engine                                                          //
// ------------------------------------------------------------------ //

test("useHalCanvas injects real pins and seeds file signals", () => {
  const text = readEditor("useHalCanvas.ts");
  assert.ok(!/mockPins/i.test(text), "canvas must not reference the deleted mock palette");
  assert.match(text, /function setPins\(/, "palette must be injectable (setPins)");
  assert.match(text, /function seedSignals\(/, "canvas must seed the file's existing signals");
  assert.match(text, /function reset\(/, "canvas must support reset-to-backend-truth");
  assert.match(
    text,
    /connectWire\(fromPortId: string, toPortId: string, label\?: string\)/,
    "connectWire must carry the seeded signal-name label",
  );
});

test("useHalCanvas supports editing and serializing signals for save", () => {
  const text = readEditor("useHalCanvas.ts");
  assert.match(text, /function renameNode\(/, "a signal block's name must be renameable");
  assert.match(text, /function renameSignal\(/, "a direct pin->pin wire's name must be renameable");
  assert.match(text, /function serializeSignals\(/, "canvas must serialize signals for saving");
  assert.match(
    text,
    /function autoNameUnnamedSignals\(/,
    "an unnamed net must be named from its pins rather than dropped",
  );
  assert.match(text, /dirty/, "canvas must track a dirty flag for the Save button");
  assert.match(
    text,
    /kind !== "hal-pin"/,
    "serialization must skip wires touching gate blocks (normal signals only, per scope)",
  );
  // A signal block is the canonical shape — seeding must build one so
  // a file's net and a hand-drawn net look and behave identically.
  assert.match(
    text,
    /addNode\("signal"/,
    "seeding must render each net as a named signal block",
  );
});

// ------------------------------------------------------------------ //
// View wiring                                                            //
// ------------------------------------------------------------------ //

test("VisualHalEditor requires a file, is machine-gated, and offers Refresh", () => {
  const text = read("views/VisualHalEditor.vue");

  assert.match(text, /route\.query\.file/, "editor must read the target file from the route query");
  assert.match(text, /hasValidTarget/, "editor must guard against a missing file");
  assert.match(text, /MachineGate/, "editor must be wrapped in MachineGate (HAL pins are :8000 data)");
  assert.match(text, /loadHalLayout\(file\.value\)/, "view must load through the adapter, scoped to the file");
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

test("VisualHalEditor offers Save / Save & Close / Close, mirroring EditorView", () => {
  const text = read("views/VisualHalEditor.vue");

  assert.match(text, /Save &amp; Close</, "Save & Close button must exist");
  assert.match(text, /@click="saveAndCloseEditor"/, "Save & Close must call saveAndCloseEditor");
  assert.match(text, />Save</, "Save button must exist");
  assert.match(text, /@click="saveEditor"/, "Save must call saveEditor");
  assert.match(text, />Close</, "Close button must exist");
  assert.match(text, /@click="confirmClose"/, "Close must go through the unsaved-changes confirm");

  assert.match(text, /HalVisualService\.saveLayout\(/, "saveEditor must call the facade's saveLayout");
  assert.match(
    text,
    /useUnsavedChangesGuard\(\(\) => canvas\.dirty\.value\)/,
    "leaving with unsaved changes must be guarded",
  );
  assert.match(text, /data-test="hal-signal-name"/, "signal names must be editable inline");
});

// ------------------------------------------------------------------ //
// Behavioural: rename -> save round-trip, including placeholder pins    //
// ------------------------------------------------------------------ //
//
// Regression guard for a real bug caught during manual verification:
// a signal's source/target pin can be a "placeholder" the backend
// synthesizes when a `.hal` file references a pin name that isn't in
// the live/mock catalog (e.g. a `webgui.*` pin under a machine's
// mock hardware). `loadHalData.ts` used to only fold `in_pins`/
// `out_pins` into the flat `pins` list `useHalCanvas` looks pins up
// from — a placeholder embedded only inside a signal's `source`/
// `targets` never made it in, so `serializeSignals()` silently
// dropped the whole wire on save. These two tests exercise the real
// modules end-to-end (skipped when the generated client isn't
// present) to make sure that stays fixed.

test("(skipped without generated client) behavioural: placeholder pins are foldable into the flat pin list", async (t) => {
  if (!existsSync(generatedPath)) {
    t.skip("generated/api not present — behavioural assertions need the real client");
    return;
  }

  const facadeUrl = pathToFileURL(resolve(src, "facades/halFacade.ts")).href;
  const facadeModule = await import(facadeUrl);
  const HalVisualService = facadeModule.default;

  const knownSourcePin = {
    id: "motion.spindle-on",
    component_name: "motion",
    pin_name: "spindle-on",
    full_name: "motion.spindle-on",
    direction: "out",
    type: "bit",
    value: true,
    description: "",
  };
  // Not present in in_pins/out_pins — only referenced by the signal,
  // exactly like the backend's synthesized placeholder.
  const placeholderTargetPin = {
    id: "webgui.spindle-on",
    component_name: "",
    pin_name: "webgui.spindle-on",
    full_name: "webgui.spindle-on",
    direction: "in",
    type: "bit",
    value: null,
    description: "Not present in current HAL introspection.",
  };

  const originalFetchLayout = HalVisualService.fetchLayout;
  HalVisualService.fetchLayout = async () => ({
    in_pins: [],
    out_pins: [knownSourcePin],
    signals: [
      {
        name: "spindle-on",
        type: "bit",
        source: knownSourcePin,
        targets: [placeholderTargetPin],
        description: "",
      },
    ],
  });

  try {
    const loaderUrl = pathToFileURL(resolve(editorDir, "loadHalData.ts")).href;
    const { loadHalLayout } = await import(loaderUrl);
    const data = await loadHalLayout("example/configs/webgui_connections.hal");

    assert.ok(data, "loadHalLayout must resolve");
    const ids = data.pins.map((p) => p.id);
    assert.ok(ids.includes("motion.spindle-on"), "known catalog pin must be present");
    assert.ok(
      ids.includes("webgui.spindle-on"),
      "the placeholder pin (only referenced by the signal) must also be folded into the flat pin list",
    );
  } finally {
    HalVisualService.fetchLayout = originalFetchLayout;
  }
});

test("(skipped without generated client) behavioural: seed -> rename -> serialize round-trip", async (t) => {
  if (!existsSync(generatedPath)) {
    t.skip("generated/api not present — behavioural assertions need the real client");
    return;
  }

  const canvasUrl = pathToFileURL(resolve(editorDir, "useHalCanvas.ts")).href;
  const { useHalCanvas } = await import(canvasUrl);

  const sourcePin = {
    id: "motion.spindle-on",
    fullName: "motion.spindle-on",
    type: "bit",
    direction: "out",
  };
  // A placeholder pin, exactly as `loadHalData.ts` now folds it in —
  // this is the case the bug above dropped silently.
  const placeholderTargetPin = {
    id: "webgui.spindle-on",
    fullName: "webgui.spindle-on",
    type: "bit",
    direction: "in",
  };

  const canvas = useHalCanvas();
  canvas.setPins([sourcePin, placeholderTargetPin]);
  const { incomplete } = canvas.seedSignals([
    { name: "spindle-on", source: sourcePin, targets: [placeholderTargetPin] },
  ]);
  canvas.clearDirty();

  assert.equal(incomplete, 0, "a well-formed net must seed without conflicts");
  assert.equal(canvas.dirty.value, false, "seeding must not mark the canvas dirty");

  // The net is rendered as a named signal block wired between its
  // pins — the same shape the operator builds by hand.
  const signalNode = canvas.nodes.find((n) => n.kind === "signal");
  assert.ok(signalNode, "the seeded net must render as a signal block");
  assert.equal(signalNode.label, "spindle-on", "the block carries the net's name");

  // Round-trips before any edit: what was seeded is what would be saved.
  const asSeeded = canvas.serializeSignals();
  assert.equal(asSeeded.length, 1, "a seeded net must serialize back out unchanged");
  assert.equal(asSeeded[0].name, "spindle-on");
  assert.equal(asSeeded[0].source, "motion.spindle-on");
  assert.deepEqual(asSeeded[0].targets, ["webgui.spindle-on"]);

  canvas.renameNode(signalNode.id, "spindle-forward");
  assert.equal(canvas.dirty.value, true, "renaming a signal must mark the canvas dirty");

  const signals = canvas.serializeSignals();
  assert.equal(signals.length, 1, "the renamed signal must survive serialization");
  assert.equal(signals[0].name, "spindle-forward");
  assert.equal(signals[0].source, "motion.spindle-on");
  assert.deepEqual(signals[0].targets, ["webgui.spindle-on"]);
});

test("(skipped without generated client) behavioural: a hand-built signal block serializes", async (t) => {
  if (!existsSync(generatedPath)) {
    t.skip("generated/api not present — behavioural assertions need the real client");
    return;
  }

  const canvasUrl = pathToFileURL(resolve(editorDir, "useHalCanvas.ts")).href;
  const { useHalCanvas } = await import(canvasUrl);

  const sourcePin = { id: "motion.spindle-on", fullName: "motion.spindle-on", type: "bit", direction: "out" };
  const targetPin = { id: "vfd.run", fullName: "vfd.run", type: "bit", direction: "in" };

  // Exactly the operator's flow: drop a Signal block, wire a writer
  // pin into it and a reader pin out of it, then name it.
  const canvas = useHalCanvas();
  canvas.setPins([sourcePin, targetPin]);
  const block = canvas.addNode("signal");

  assert.equal(block.label, "", "a fresh signal block starts unnamed");
  assert.ok(canvas.connectToPin(block.inputs[0].id, sourcePin).ok, "wiring the writer pin in must succeed");
  assert.ok(canvas.connectToPin(block.outputs[0].id, targetPin).ok, "wiring the reader pin out must succeed");

  canvas.renameNode(block.id, "spindle-run");
  const signals = canvas.serializeSignals();
  assert.equal(signals.length, 1, "a hand-built signal block must serialize");
  assert.equal(signals[0].name, "spindle-run");
  assert.equal(signals[0].source, "motion.spindle-on");
  assert.deepEqual(signals[0].targets, ["vfd.run"]);
});

test("(skipped without generated client) behavioural: an unnamed net is named from its pins", async (t) => {
  if (!existsSync(generatedPath)) {
    t.skip("generated/api not present — behavioural assertions need the real client");
    return;
  }

  const canvasUrl = pathToFileURL(resolve(editorDir, "useHalCanvas.ts")).href;
  const { useHalCanvas } = await import(canvasUrl);

  const sourcePin = { id: "motion.spindle-on", fullName: "motion.spindle-on", type: "bit", direction: "out" };
  const targetPin = { id: "vfd.run", fullName: "vfd.run", type: "bit", direction: "in" };

  const canvas = useHalCanvas();
  canvas.setPins([sourcePin, targetPin]);
  const block = canvas.addNode("signal");
  canvas.connectToPin(block.inputs[0].id, sourcePin);
  canvas.connectToPin(block.outputs[0].id, targetPin);

  assert.equal(canvas.autoNameUnnamedSignals(), 1, "the wired-but-unnamed net must be named");
  // Writer first, then its readers; dots become dashes so the result
  // is a legal HAL name that still says what the net does.
  assert.equal(block.label, "motion-spindle-on-vfd-run");

  const signals = canvas.serializeSignals();
  assert.equal(signals.length, 1, "the auto-named net must be written, not dropped");
  assert.equal(signals[0].name, "motion-spindle-on-vfd-run");
  assert.equal(signals[0].source, "motion.spindle-on");
  assert.deepEqual(signals[0].targets, ["vfd.run"]);

  // Re-running is a no-op: a name, once assigned, is never rewritten.
  assert.equal(canvas.autoNameUnnamedSignals(), 0);
  assert.equal(block.label, "motion-spindle-on-vfd-run");
});

test("(skipped without generated client) behavioural: derived names stay unique and HAL-legal", async (t) => {
  if (!existsSync(generatedPath)) {
    t.skip("generated/api not present — behavioural assertions need the real client");
    return;
  }

  const canvasUrl = pathToFileURL(resolve(editorDir, "useHalCanvas.ts")).href;
  const { useHalCanvas } = await import(canvasUrl);

  // Two writers whose derived names would collide, plus a pin pair
  // long enough to overflow LinuxCNC's HAL_NAME_LEN.
  const shortOut = { id: "a.out", fullName: "a.out", type: "bit", direction: "out" };
  const shortIn = { id: "b.in", fullName: "b.in", type: "bit", direction: "in" };
  const longOut = {
    id: "verylongcomponent.a-very-long-writer-pin-name",
    fullName: "verylongcomponent.a-very-long-writer-pin-name",
    type: "bit",
    direction: "out",
  };
  const longIn = {
    id: "anotherlongcomponent.a-very-long-reader-pin-name",
    fullName: "anotherlongcomponent.a-very-long-reader-pin-name",
    type: "bit",
    direction: "in",
  };

  const canvas = useHalCanvas();
  canvas.setPins([shortOut, shortIn, longOut, longIn]);

  // A hand-typed name that squats on the string the next net derives.
  const taken = canvas.addNode("signal");
  canvas.renameNode(taken.id, "a-out-b-in");

  const collides = canvas.addNode("signal");
  canvas.connectToPin(collides.inputs[0].id, shortOut);
  canvas.connectToPin(collides.outputs[0].id, shortIn);

  const long = canvas.addNode("signal");
  canvas.connectToPin(long.inputs[0].id, longOut);
  canvas.connectToPin(long.outputs[0].id, longIn);

  assert.equal(canvas.autoNameUnnamedSignals(), 2);
  assert.equal(collides.label, "a-out-b-in-2", "a taken name must be suffixed, never duplicated");
  assert.ok(long.label.length <= 47, `derived name must fit HAL_NAME_LEN, got ${long.label.length}`);
  assert.notEqual(long.label, collides.label);
  assert.match(long.label, /^[a-z0-9_-]+$/, "a derived name must be a legal HAL name");
});

// ------------------------------------------------------------------ //
// Per-file entry point (no more standalone sidebar page)                 //
// ------------------------------------------------------------------ //

test("the sidebar no longer lists a standalone HAL Editor entry", () => {
  const text = read("components/AppSidebar.vue");
  assert.doesNotMatch(
    text,
    /id:\s*'hal-editor'/,
    "AppSidebar must not list hal-editor — it's opened per-file from the machine file browser",
  );
});

test("MachinesExplorer opens the Visual HAL Editor for .hal files", () => {
  const text = read("components/machineconfig/MachinesExplorer.vue");
  assert.match(text, /isHalFile/, "explorer must detect .hal files");
  assert.match(
    text,
    /router\.push\(\{\s*name:\s*"hal-editor",\s*query:\s*\{\s*file:\s*entry\.path\s*\}\s*\}\)/,
    "opening a .hal file must route to hal-editor with its path as the file query param",
  );
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
  // The facade survives — it is the editor's only network path.
  assert.ok(existsSync(resolve(src, "facades/halFacade.ts")), "facades/halFacade.ts must stay");
});
