// Contract tests for the shared MacroButton primitives in
// ``frontend/src/ui/``.
//
// These are static-source regex assertions, mirroring the style of
// ``test-ui-primitives.mjs`` — the runtime Vue behaviour is
// verified by the Vite build and the dashboard's manual QA matrix.
//
// What we assert here:
//
//   * ``MacroButton.vue`` documents the visibility contract
//     (descriptor falsy / disabled / empty → render nothing).
//   * The button reuses the shared ``BaseButton`` primitive so a future
//     palette change propagates automatically.
//   * The icon-rendering branch falls through to a literal
//     ``<span>`` so emoji / unicode glyphs render without a new
//     icon set entry.
//   * The button list persists as the ``machine.macro_buttons`` UI
//     setting (``MacroButtonsSetting``), normalising bad data to ``[]``.
//   * ``MacroButtonEditor`` drives row count from its ``slots``
//     prop and emits ``update:modelValue`` on commit (not per
//     keystroke).
//   * ``ui/index.ts`` re-exports ``MacroButton`` and
//     ``MacroButtonEditor`` so callers import from the shared barrel.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");

const buttonPath = resolve(repoRoot, "frontend/src/ui/MacroButton.vue");
const editorPath = resolve(repoRoot, "frontend/src/ui/MacroButtonEditor.vue");
const typesPath = resolve(repoRoot, "frontend/src/ui/macroButtonTypes.ts");
const settingTypePath = resolve(repoRoot, "frontend/src/settings/types/MacroButtonsSetting.ts");
const settingEditorPath = resolve(repoRoot, "frontend/src/settings/components/SettingMacroButtons.vue");
const definitionsPath = resolve(repoRoot, "frontend/src/settings/definitions/machine.ts");
const indexPath = resolve(repoRoot, "frontend/src/ui/index.ts");

function read(path) {
  return readFileSync(path, "utf-8");
}

const buttonText = read(buttonPath);
const editorText = read(editorPath);
const typesText = read(typesPath);
const settingTypeText = read(settingTypePath);
const settingEditorText = read(settingEditorPath);
const definitionsText = read(definitionsPath);
const indexText = read(indexPath);

// ---------------------------------------------------------------- //
// MacroButton.vue                                                    //
// ---------------------------------------------------------------- //

test("MacroButton hides itself when the descriptor is missing or disabled", () => {
  // The visibility contract is the public promise every host
  // relies on: a missing / disabled / empty descriptor must not
  // render a phantom button. We assert the three conditions
  // appear in the same computed / v-if guard so a regression
  // that flips them to "rendered" trips the test.
  assert.match(buttonText, /isVisible/, "MacroButton must compute isVisible");
  // both renderings (the output control and the button) are gated on it
  assert.match(
    buttonText,
    /v-if="isVisible && descriptor\?\.macroKind === 'output'"/,
    "MacroButton must gate the output control on isVisible",
  );
  assert.match(buttonText, /v-else-if="isVisible"/, "MacroButton must gate the button on isVisible");
  assert.match(buttonText, /isMacroButtonComplete\(props\.descriptor\)/);
});

test("a button without a label or an action is not shown and is flagged red (#126)", async () => {
  const { isMacroButtonComplete, macroButtonProblems } = await import(pathToFileURL(typesPath).href);
  const full = { slot: "a", enabled: true, name: "Light", macroName: "light" };
  assert.equal(isMacroButtonComplete(full), true);
  assert.equal(isMacroButtonComplete({ ...full, enabled: false }), false);
  assert.equal(isMacroButtonComplete({ ...full, name: "  " }), false);
  assert.equal(isMacroButtonComplete({ ...full, macroName: "" }), false);
  assert.equal(isMacroButtonComplete(null), false);
  assert.deepEqual(macroButtonProblems({ name: "", macroName: "" }), { missingLabel: true, missingAction: true });
  // the editor flags only enabled rows, on the name input and the action select
  assert.match(editorText, /row\?\.enabled \? macroButtonProblems\(row\) : NO_PROBLEMS/);
  assert.match(editorText, /problemsFor\(slot\)\.missingLabel \? INVALID : VALID/);
  assert.match(editorText, /problemsFor\(slot\)\.missingAction \? INVALID : VALID/);
  assert.match(editorText, /macro-button-problem-/);
});

test("MacroButton dispatches via useMacrosStore.runMacroOfKind", () => {
  // Click routing is the second half of the contract: a click
  // must call ``runMacroOfKind(kind, name)`` so the E-Stop guard
  // and the .macro / .ngc dispatch paths in the macros store
  // apply uniformly. The actual call spans two lines in the
  // source so the regex tolerates whitespace.
  assert.match(
    buttonText,
    /useMacrosStore/,
    "MacroButton must import useMacrosStore",
  );
  assert.match(
    buttonText,
    /macrosStore\.runMacroOfKind\([\s\S]*?props\.descriptor\.macroKind[\s\S]*?props\.descriptor\.macroName[\s\S]*?\)/,
    "MacroButton must call runMacroOfKind(macroKind, macroName)",
  );
});

test("MacroButton reuses the shared BaseButton primitive", () => {
  // Style consistency is the whole point of the shared UI layer.
  // The primitive must wrap ``<BaseButton>`` so a future palette /
  // sizing tweak propagates to every host.
  assert.match(buttonText, /import BaseButton from "\.\/BaseButton\.vue"/);
  assert.match(
    buttonText,
    /<BaseButton\b/,
    "MacroButton must render the shared BaseButton primitive",
  );
});

test("MacroButton accepts the documented variants and sizes", () => {
  // Match the ``<BaseButton>`` primitive's contract so a host can
  // request any variant / size that matches its siblings.
  for (const v of ["primary", "success", "danger", "secondary", "ghost"]) {
    assert.match(
      buttonText,
      new RegExp(`\\b${v}\\b`),
      `MacroButton must accept variant ${v}`,
    );
  }
  for (const s of ["sm", "md", "lg"]) {
    assert.match(
      buttonText,
      new RegExp(`\\b${s}\\b`),
      `MacroButton must accept size ${s}`,
    );
  }
});

test("MacroButton falls back to literal text for non-icon glyphs", () => {
  // Operators can drop emoji (``💡``, ``🔦``) or unicode glyphs
  // (``▶``, ``★``) into the icon field. The renderer must
  // accept anything that doesn't match the known ``<Icon>`` set
  // and render it verbatim so we never have to maintain a
  // separate emoji dictionary.
  assert.match(
    buttonText,
    /iconIsKnown/,
    "MacroButton must compute iconIsKnown",
  );
  assert.match(
    buttonText,
    /v-else-if="descriptor\?\.icon"/,
    "MacroButton must render a literal span for unknown glyphs",
  );
});

test("MacroButton honours the E-Stop and busy guards", () => {
  // The macros store already guards dispatch with the E-Stop
  // check; the button additionally flips itself disabled so the
  // operator sees the muted visual. ``isBusy`` guards against
  // double-click dispatch while another macro is running.
  assert.match(
    buttonText,
    /machineStore\.isEstopActive/,
    "MacroButton must check isEstopActive",
  );
  assert.match(
    buttonText,
    /macrosStore\.isBusy/,
    "MacroButton must check macrosStore.isBusy",
  );
});

// ---------------------------------------------------------------- //
// machine.macro_buttons setting                                      //
// ---------------------------------------------------------------- //

test("macro buttons persist as the machine.macro_buttons UI setting", () => {
  // One list for every slot (DRO rows + viewer slots): two lists
  // sharing one store would overwrite each other's rows on save.
  assert.match(definitionsText, /new MacroButtonsSetting\(/);
  assert.match(definitionsText, /"machine\.macro_buttons"/);
  for (const slot of ["dro.x", "dro.y", "dro.z", "viewer.1", "viewer.2", "viewer.3", "camera.1", "camera.2", "camera.3"]) {
    assert.ok(definitionsText.includes(`"${slot}"`), `slot ${slot} must be declared`);
  }
  // Hosts look buttons up by slot.
  assert.match(settingTypeText, /get bySlot\(\)/);
});

test("stored macro buttons are normalised, bad data becomes []", () => {
  assert.match(typesText, /export function normaliseMacroButtons\(/);
  assert.match(typesText, /if \(!Array\.isArray\(raw\)\) return \[\];/);
  assert.match(settingTypeText, /normaliseMacroButtons\(raw\)/);
});

test("the setting editor saves only on the editor's commit, never from a watcher", () => {
  // Regression guard for the old request-spam loop: a deep watcher on
  // the button list that persisted on every change fired ~100 PUTs per
  // click. The only save path is the editor's update:modelValue.
  assert.match(settingEditorText, /@update:model-value="onUpdate"/);
  assert.match(settingEditorText, /setting\.save\(next\)/);
  assert.doesNotMatch(settingEditorText, /\bwatch\(/);
});

// ---------------------------------------------------------------- //
// MacroButtonEditor.vue                                              //
// ---------------------------------------------------------------- //

test("MacroButtonEditor drives row count from the slots prop", () => {
  // The editor renders one row per slot. The test asserts the
  // ``v-for="slot in slots"`` loop and the per-row id binding
  // so a regression that switches to ``v-for="button in modelValue"``
  // (which would only render configured rows) trips here.
  assert.match(
    editorText,
    /v-for="slot in slots"/,
    "MacroButtonEditor must iterate over the slots prop",
  );
  assert.match(
    editorText,
    /:data-test="`macro-button-row-\$\{slot\.id\}`"/,
    "MacroButtonEditor must bind the row's data-test to slot.id",
  );
});

test("MacroButtonEditor emits update:modelValue on commit", () => {
  // v-model integration is the contract every parent uses.
  // The editor must declare ``update:modelValue`` as an emitted
  // event and emit it through a commit handler (not on every
  // keystroke).
  assert.match(
    editorText,
    /defineEmits\(\[\s*"update:modelValue"\s*\]\)/,
    "MacroButtonEditor must declare the update:modelValue emit",
  );
  assert.match(
    editorText,
    /emit\(\s*"update:modelValue"\s*,\s*draft\.value/,
    "MacroButtonEditor must emit the working draft",
  );
});

test("MacroButtonEditor offers macro, ngc and UI component (no mcode)", () => {
  // ``mcode`` is intentionally excluded: an operator who needs an M-code
  // call wraps it in a ``.macro``. "UI component" opens a panel in a window.
  assert.match(editorText, /\{ value: "macro", label: "macro" \}/);
  assert.match(editorText, /\{ value: "ngc", label: "ngc" \}/);
  assert.match(editorText, /\{ value: "component", label: "UI component" \}/);
  assert.match(editorText, /<option v-for="kind in KINDS" :key="kind\.value" :value="kind\.value">/);
  assert.doesNotMatch(editorText, /value: "mcode"|<option value="mcode">/, "no mcode kind");
  assert.match(editorText, /if \(row\?\.macroKind === "component"\) return componentOptions;/,
    "kind component lists the panels");
});

test("a component button opens its panel in a floating window", () => {
  const button = readFileSync(resolve(here, "../src/ui/MacroButton.vue"), "utf-8");
  assert.match(button, /floating\.open\(panel, props\.descriptor\.name \|\| panelDef\(panel\)\?\.label \|\| panel\)/);
  assert.match(button, /opensComponent\.value \? false :/, "opening a window is never blocked by the E-stop");
  const host = readFileSync(resolve(here, "../src/components/FloatingPanelHost.vue"), "utf-8");
  assert.match(host, /provide\(WINDOW_CHROME, props\.chrome\)/, "the window hands its x / drag to the panel");
  assert.match(host, /<header\s+v-if="!claims\[win\.id\]"/, "its own header only while nothing took the hook");
  assert.match(host, /<MachineGate v-else-if="PANEL_COMPONENTS\[win\.panel\]"/);
  const card = readFileSync(resolve(here, "../src/ui/BaseCard.vue"), "utf-8");
  assert.match(card, /v-if="title \|\| chrome"/, "a card header shows when it has a title or the window's x");
  assert.match(card, /@pointerdown="chrome\?\.startDrag\(\$event\)"/, "dragging the card header moves the window");
  assert.match(card, /<WindowCloseButton v-if="chrome" :chrome="chrome" \/>/);
  // every window in one z-30 layer: the sidebar (z-40) and the E-stop box (z-[100]) stay above
  assert.match(host, /class="pointer-events-none fixed inset-0 z-30" data-testid="floating-panel-layer"/);
  assert.match(host, /zIndex: win\.z,/);
  assert.match(readFileSync(resolve(here, "../src/App.vue"), "utf-8"), /<AppSidebar class="absolute top-0 left-0 h-full z-40/);
  assert.match(readFileSync(resolve(here, "../src/components/EStopHeader.vue"), "utf-8"), /data-estop-overlay class="fixed top-0 right-0 z-\[100\]/);
  const hook = readFileSync(resolve(here, "../src/composables/windowChrome.ts"), "utf-8");
  assert.match(hook, /provide\(WINDOW_CHROME, null\);/, "only the outermost card takes it");
  assert.match(readFileSync(resolve(here, "../src/App.vue"), "utf-8"), /<FloatingPanelHost \/>/);
});

test("MacroButtonEditor stores the bare macro name, not the file name", () => {
  // The list rows are the shared file DTO: ``name`` = "probe.ngc",
  // ``macro_name`` = "probe". Saving ``name`` made the run endpoint 404.
  assert.match(editorText, /\.map\(\(row\) => row\?\.macro_name\)/);
  assert.doesNotMatch(editorText, /\.map\(\(row\) => row\?\.name\)/);
  assert.match(editorText, /stripExtension\(r\.macroName, macroKind\)/, "old rows with an extension are cleaned up");
});

test("MacroButtonEditor fetches macro options via the macros facade", () => {
  // Regression guard for the "dropdown does nothing" bug: the
  // editor used to source options from the macros Pinia store,
  // which is only populated when the macros module has booted.
  // Settings tabs that mount before ``useMacrosStore()`` ran
  // ended up with an empty dropdown. The fix is to list them through
  // ``macrosFacade.list`` (no store) so the editor no longer depends on
  // the macros module's lifecycle.
  assert.match(
    editorText,
    /import\s*\{[^}]*\bmacrosFacade\b[^}]*\}\s*from\s*["'][^"']*facades\/macrosFacade["']/,
    "MacroButtonEditor must import macrosFacade",
  );
  // The two calls — ``macro`` for the .macro dropdown and
  // ``ngc`` for the .ngc dropdown — must both be present. ``mcode``
  // is intentionally excluded (the operator wraps mcode calls in
  // .macro files instead).
  assert.match(
    editorText,
    /macrosFacade\.list\(\s*["']macro["']\s*\)/,
    "MacroButtonEditor must list the 'macro' kind",
  );
  assert.match(
    editorText,
    /macrosFacade\.list\(\s*["']ngc["']\s*\)/,
    "MacroButtonEditor must list the 'ngc' kind",
  );
  assert.doesNotMatch(
    editorText,
    /\.list\(\s*["']mcode["']\s*\)/,
    "MacroButtonEditor must not request the mcode list",
  );
  // And the editor must NOT depend on the macros Pinia store.
  assert.doesNotMatch(
    editorText,
    /useMacrosStore/,
    "MacroButtonEditor must not import useMacrosStore (bypass the store)",
  );
});

test("MacroButtonEditor scopes dropdown options to the row's macroKind", () => {
  // Each row's macro dropdown must filter by the row's
  // ``macroKind`` so a ``.macro`` row never silently lands a
  // ``.ngc`` selection. The template reads from
  // ``optionsFor(descriptorFor(slot))`` and the helper maps
  // ``row.macroKind`` to the matching pre-sorted list.
  assert.match(
    editorText,
    /optionsFor\(\s*descriptorFor\(slot\)\s*\)/,
    "MacroButtonEditor must feed the dropdown from optionsFor(descriptorFor(slot))",
  );
  assert.match(
    editorText,
    /function\s+optionsFor\s*\(/,
    "MacroButtonEditor must define the optionsFor helper",
  );
  assert.match(
    editorText,
    /macroOptionsByKind/,
    "MacroButtonEditor must keep per-kind dropdown option lists",
  );
});

// ---------------------------------------------------------------- //
// ui/index.ts barrel                                                 //
// ---------------------------------------------------------------- //

test("ui/index.ts re-exports MacroButton and MacroButtonEditor", () => {
  for (const name of ["MacroButton", "MacroButtonEditor"]) {
    assert.match(
      indexText,
      new RegExp(`export\\s+\\{\\s*default\\s+as\\s+${name}`),
      `ui barrel must re-export ${name}`,
    );
  }
  // The old per-module composable is gone (replaced by the setting).
  assert.doesNotMatch(indexText, /useMacroButtonConfig/);
});

test("the camera view shows the three camera macro slots bottom-left", () => {
  const text = readFileSync(resolve(repoRoot, "frontend/src/components/camera/CameraViewer.vue"), "utf-8");
  assert.match(text, /\["camera\.1", "camera\.2", "camera\.3"\]/);
  assert.match(text, /macroButtons\.bySlot/);
  assert.match(text, /class="absolute bottom-4 left-4[^"]*"[^>]*data-test="camera-macro-buttons"/);
  assert.match(text, /<MacroButton[\s\S]{0,80}:descriptor="buttonsBySlot\[slot\]"/);
});


test("kind 'output': a toggle, slider or colour picker next to the name", async () => {
  const editor = editorText;
  assert.match(editor, /\{ value: "output", label: "Output pin" \}/);
  assert.match(editor, /outputTargets\(baseThread\.io, baseThread\.leds\)/, "the machine's outputs from its live state");
  const control = readFileSync(resolve(here, "../src/ui/OutputControl.vue"), "utf-8");
  for (const id of ["output-toggle", "output-slider", "output-color"]) {
    assert.ok(control.includes(':data-testid="`' + id + '-${descriptor.slot}`"'), id);
  }
  assert.match(control, /<span v-if="descriptor\.name && !compact" class="whitespace-nowrap"/,
    "the name next to the control — hidden when the row has no room for it");
  assert.match(control, /const overflowing = \(\) => ancestors\(\)\.some\(\(el\) => el\.scrollWidth - el\.clientWidth > 1\);/);
  assert.match(control, /:title="target \? descriptor\.name \|\| target\.label/, "the name stays the tooltip");
  const { outputTargets, findTarget } = await import(pathToFileURL(resolve(here, "../src/ui/outputTargets.ts")).href);
  const io = { outputs: [{ id: "light", pwm: false, value: 1 }, { id: "beeper", pwm: true, scale: 0.5, value: 0 }],
               fans: [{ id: "fan", value: 40 }], inputs: [] };
  const leds = [{ id: "sb", chain_count: 3, color_order: "GRB", segments: [] }];
  const targets = outputTargets(io, leds);
  assert.deepEqual(targets.map((t: { value: string; control: string }) => [t.value, t.control]),
    [["out:light", "toggle"], ["out:beeper", "slider"], ["fan:fan", "slider"], ["led:sb", "color"]]);
  assert.equal(findTarget("out:beeper", io, leds).max, 0.5, "a PWM pin's slider goes to its scale");
  assert.equal(findTarget("fan:fan", io, leds).max, 100);
  assert.equal(findTarget("out:nope", io, leds), undefined);
});
