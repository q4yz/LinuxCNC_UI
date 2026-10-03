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
import { fileURLToPath } from "node:url";

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
  assert.match(
    buttonText,
    /v-if="isVisible"/,
    "MacroButton must gate the template on isVisible",
  );
  assert.match(
    buttonText,
    /descriptor != null/,
    "MacroButton must null-check the descriptor",
  );
  assert.match(
    buttonText,
    /descriptor\.enabled === true/,
    "MacroButton must check descriptor.enabled === true",
  );
  assert.match(
    buttonText,
    /descriptor\.macroName \?\? ""\)\.length > 0/,
    "MacroButton must check descriptor.macroName is non-empty",
  );
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
  for (const slot of ["dro.x", "dro.y", "dro.z", "viewer.1", "viewer.2", "viewer.3"]) {
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

test("MacroButtonEditor filters the macro dropdown to macro + ngc only", () => {
  // ``mcode`` is intentionally excluded from the per-slot
  // dropdown: an operator who needs an M-code call wraps it in
  // a ``.macro``. The kind picker should also offer only the
  // two supported kinds.
  assert.match(
    editorText,
    /<option value="macro">macro<\/option>/,
    "MacroButtonEditor must offer macro in the kind picker",
  );
  assert.match(
    editorText,
    /<option value="ngc">ngc<\/option>/,
    "MacroButtonEditor must offer ngc in the kind picker",
  );
  assert.doesNotMatch(
    editorText,
    /<option value="mcode">mcode<\/option>/,
    "MacroButtonEditor must not offer mcode (wrap in a .macro instead)",
  );
});

test("MacroButtonEditor fetches macro options via the generated client", () => {
  // Regression guard for the "dropdown does nothing" bug: the
  // editor used to source options from the macros Pinia store,
  // which is only populated when the macros module has booted.
  // Settings tabs that mount before ``useMacrosStore()`` ran
  // ended up with an empty dropdown. The fix is to call the
  // generated OpenAPI client directly via
  // ``ModulesMacrosService.listMacros`` so the editor no longer
  // depends on the macros module's lifecycle.
  assert.match(
    editorText,
    /import\s*\{[^}]*\bModulesMacrosService\b[^}]*\}\s*from\s*["'][^"']*generated\/api["']/,
    "MacroButtonEditor must import ModulesMacrosService from the generated client",
  );
  // The two calls — ``macro`` for the .macro dropdown and
  // ``ngc`` for the .ngc dropdown — must both be present. ``mcode``
  // is intentionally excluded (the operator wraps mcode calls in
  // .macro files instead).
  assert.match(
    editorText,
    /listMacros\(\s*["']macro["']\s*\)/,
    "MacroButtonEditor must call listMacros('macro')",
  );
  assert.match(
    editorText,
    /listMacros\(\s*["']ngc["']\s*\)/,
    "MacroButtonEditor must call listMacros('ngc')",
  );
  assert.doesNotMatch(
    editorText,
    /listMacros\(\s*["']mcode["']\s*\)/,
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
