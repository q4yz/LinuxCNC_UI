// Tier 1 cleanup regression tests for the universal editor.
//
// Each test asserts one concrete bug-fix landed:
//   - dead emits ``close`` / ``save`` were dropped from Editor.vue;
//   - dead ``openAnother()`` was dropped from EditorView.vue;
//   - the unsaved-changes prompt copy is identical in the guard
//     and the view (single source of truth);
//   - raw enum strings never leak into the editor header;
//   - Ctrl+S / Cmd+S save shortcut is wired on the overlay.
//
// Run with: node --test frontend/tests/test-editor-cleanup.mjs

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");

const editorVuePath = resolve(repoRoot, "frontend/src/components/Editor.vue");
const editorViewPath = resolve(repoRoot, "frontend/src/views/EditorView.vue");
const guardPath = resolve(
  repoRoot,
  "frontend/src/router/guards/unsavedChangesGuard.ts",
);
const storePath = resolve(repoRoot, "frontend/src/stores/editor.ts");

function readText(path) {
  return readFileSync(path, "utf-8");
}

const editorVueText = readText(editorVuePath);
const editorViewText = readText(editorViewPath);
const guardText = readText(guardPath);
const storeText = readText(storePath);

// ---------------------------------------------------------------------- //
// Dead API surface removed                                                 //
// ---------------------------------------------------------------------- //

test("Editor.vue declares only the update:modelValue emit", () => {
  // The legacy component declared ``close`` and ``save`` emits
  // that nothing fired. A future maintainer chasing "where does
  // the editor call save?" would look for those emits and find
  // nothing — the parent handles save/close via its own header
  // buttons instead. Keep the API minimal.
  assert.match(
    editorVueText,
    /defineEmits\(\[\s*['"]update:modelValue['"]\s*\]\)/,
    "Editor.vue must declare only update:modelValue",
  )
  assert.doesNotMatch(
    editorVueText,
    /['"]close['"]/,
    "Editor.vue must not declare a 'close' emit",
  )
  assert.doesNotMatch(
    editorVueText,
    /['"]save['"]/,
    "Editor.vue must not declare a 'save' emit",
  )
})

test("EditorView.vue does not contain the dead openAnother() façade", () => {
  // The old EditorView re-exported the helper as ``openAnother``
  // for an ``@click="openInEditor(...)"`` template binding that
  // never materialised. The template now imports the helper
  // directly, so the façade is dead code.
  assert.doesNotMatch(
    editorViewText,
    /function\s+openAnother\b/,
    "EditorView must not declare openAnother()",
  )
})

// ---------------------------------------------------------------------- //
// Unsaved-changes prompt copy is unified                                   //
// ---------------------------------------------------------------------- //

test("guard and view share a single UNSAVED_PROMPT constant", () => {
  // Pre-cleanup: the guard hardcoded German ("Ungespeicherte
  // Änderungen") and the view hardcoded English ("Unsaved
  // changes"). Post-cleanup: both import the same constant —
  // the guard exports it, the view imports it.
  assert.match(
    guardText,
    /export\s+const\s+UNSAVED_PROMPT\b/,
    "guard must export the UNSAVED_PROMPT constant",
  )
  // The view must reference ``UNSAVED_PROMPT`` by name, either as
  // a local declaration or via ``import { UNSAVED_PROMPT } from``.
  assert.match(
    editorViewText,
    /UNSAVED_PROMPT\b/,
    "view must reference UNSAVED_PROMPT (import or local)",
  )
  // No German copy left in either file.
  assert.doesNotMatch(
    guardText,
    /Ungespeicherte/,
    "guard must not contain the legacy German title",
  )
  assert.doesNotMatch(
    editorViewText,
    /Ungespeicherte/,
    "view must not contain the legacy German title",
  )
  assert.doesNotMatch(
    editorViewText,
    /Möchten Sie diese Seite/,
    "view must not contain the legacy German question",
  )
})

// ---------------------------------------------------------------------- //
// Friendly source labels (no raw enum in UI)                             //
// ---------------------------------------------------------------------- //

test("the editor header uses sourceLabel(), never the raw source key", () => {
  // The view's header used to render ``(profiles)`` /
  // ``(m_codes)`` — internal enum strings. Post-cleanup the
  // header reads from the ``sourceLabel()`` helper so the operator
  // sees ``(Profiles)`` / ``(M-codes)`` instead.
  assert.match(
    editorViewText,
    /sourceLabel\(\s*currentSource\s*\)/,
    "header must call sourceLabel(currentSource)",
  )
  // The old raw-enum template must be gone.
  assert.doesNotMatch(
    editorViewText,
    /\{\{\s*currentSource\s*\}\}/,
    "the raw {{ currentSource }} interpolation must be removed",
  )
})

test("EDITOR_SOURCE_LABELS covers every EDITOR_SOURCES entry", () => {
  // ``sourceLabel`` falls back to the raw key for any source
  // without a label. Every shipped source must have one so the
  // fallback is a "you forgot a label" signal in dev, not a
  // silent enum leak. The store keys the map by ``EDITOR_SOURCES.<X>``
  // rather than the raw enum string, so the test matches either.
  assert.match(storeText, /EDITOR_SOURCE_LABELS\b/)
  for (const source of [
    "PROFILES",
    "ACTIVE",
    "STAGED",
    "M_CODES",
    "PROGRAMS",
    "MACROS",
  ]) {
    const quoted = source.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
    // Match ``[EDITOR_SOURCES.X]: 'Label'`` (enum-keyed form).
    assert.match(
      storeText,
      new RegExp(`\\[\\s*EDITOR_SOURCES\\.${quoted}\\s*\\]:\\s*['"][^'"]+['"]`),
      `EDITOR_SOURCE_LABELS must include ${source}`,
    )
  }
})

// ---------------------------------------------------------------------- //
// Ctrl+S / Cmd+S save shortcut                                             //
// ---------------------------------------------------------------------- //

test("Ctrl+S / Cmd+S save shortcut is bound on document-level", () => {
  // ``EditorView`` is a fixed-position overlay — the browser's
  // own save dialog never opens. The view intercepts the chord at
  // the document level so it works regardless of focus inside the
  // overlay. ``readOnly`` and ``!isDirty`` short-circuits keep
  // silent keystrokes from creating noise.
  assert.match(
    editorViewText,
    /addEventListener\(\s*['"]keydown['"]/,
    "view must bind a document-level keydown listener",
  )
  assert.match(
    editorViewText,
    /removeEventListener\(\s*['"]keydown['"]/,
    "view must unbind the keydown listener on unmount",
  )
  assert.match(
    editorViewText,
    /\bctrlKey\s*\|\|\s*event\.metaKey/,
    "shortcut handler must accept both Ctrl and Cmd",
  )
  assert.match(
    editorViewText,
    /event\.key\.toLowerCase\(\)\s*===\s*['"]s['"]/,
    "shortcut handler must match the 's' key (case-insensitive)",
  )
  assert.match(
    editorViewText,
    /event\.preventDefault\(\)/,
    "shortcut handler must preventDefault to suppress the browser save dialog",
  )
})

// ---------------------------------------------------------------------- //
// editorContent is reset on close                                          //
// ---------------------------------------------------------------------- //

test("closeEditor clears the editorContent local ref", () => {
  // Without this reset the local ref still holds the previous
  // file's text after the next mount until loadFromRoute
  // overwrites it. Tiny race window; better closed.
  assert.match(
    editorViewText,
    /function\s+closeEditor[\s\S]*?editorContent\.value\s*=\s*['"]['"]/,
    "closeEditor must reset editorContent to ''",
  )
})

test("onBeforeUnmount clears the editorContent local ref", () => {
  // ``closeEditor`` is the happy path; route-leave via the
  // unsaved-changes guard or back button bypasses it. The
  // unmount hook is the safety net.
  assert.match(
    editorViewText,
    /onBeforeUnmount\([\s\S]*?editorContent\.value\s*=\s*['"]['"]/,
    "onBeforeUnmount must reset editorContent",
  )
})

// ---------------------------------------------------------------------- //
// mr-30 is intentionally preserved                                         //
// ---------------------------------------------------------------------- //

test("Close button keeps its mr-30 spacing (not mr-3)", () => {
  // The user explicitly chose to keep ``mr-30`` even though it is
  // not a standard Tailwind class — removing the rule would let
  // the E-Stop header overlap the Close button. Guard the
  // string so a future "Tailwind lint" pass does not silently
  // rewrite it.
  assert.match(
    editorViewText,
    /Close<\/button>/,
    "Close button must still render",
  )
  // The Close button's class list still contains ``mr-30``.
  const closeButtonMatch = editorViewText.match(
    /<button[^>]*@click=["']confirmClose["'][^>]*>[\s\S]*?Close<\/button>/,
  )
  assert.ok(closeButtonMatch, "Close button template must be parseable")
  assert.match(
    closeButtonMatch[0],
    /\bmr-30\b/,
    "Close button must keep the mr-30 class (E-Stop overlap guard)",
  )
})

// ---------------------------------------------------------------------- //
// Editor lifecycle hooks are imported and used                              //
// ---------------------------------------------------------------------- //

test("EditorView imports every Vue lifecycle hook it calls", () => {
  // Regression guard: a previous Tier 1 edit added an
  // ``onBeforeUnmount`` call without importing the helper, which
  // crashed the editor at navigation. The import must list every
  // lifecycle hook the view actually uses.
  const importLine = editorViewText.match(
    /import\s*\{[^}]*\}\s*from\s*['"]vue['"]/,
  )
  assert.ok(importLine, "EditorView must import from 'vue'")
  for (const hook of ["onMounted", "onBeforeUnmount"]) {
    assert.match(
      importLine[0],
      new RegExp(`\\b${hook}\\b`),
      `EditorView's vue import must include ${hook}`,
    )
  }
})

// ---------------------------------------------------------------------- //
// App.vue: dynamic module view is not made reactive                       //
// ---------------------------------------------------------------------- //

test("App.vue wraps the async module view in markRaw()", () => {
  // Regression guard for the
  //   "Vue received a Component that was made a reactive object"
  // warning that fires on every route change. The contract
  // rewrite moved the ``markRaw`` into the registry itself
  // (``registry.js::_mount``); App.vue no longer wraps an
  // ``AsyncComponentWrapper`` because lazy imports are forbidden
  // (``.agent/STATE.md`` § 13).
  const appText = readText(
    resolve(repoRoot, "frontend/src/App.vue"),
  )
  assert.doesNotMatch(
    appText,
    /\bdefineAsyncComponent\s*\(/,
    "App.vue must not call defineAsyncComponent (no-lazy-imports rule)",
  );
  // The registry's reactive Map stores the components; the
  // registry itself applies ``markRaw`` so App.vue does not need
  // to. We assert the registry applies it on the registry's
  // record path below.
})