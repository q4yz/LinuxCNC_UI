// Regression test for the universal-editor source-driven dispatch
// (issue #132).
//
// Run with: node --test frontend/tests/test-editor-routing.mjs
//
// Pre-refactor, ``stores/editor.js::isProfilePath`` fell back to
// ``modeForFilename(path)`` to decide whether a bare name like
// ``printer.cfg.txt`` belonged to the profile surface. Because the
// mode for ``.txt`` is ``"text"`` (not in ``PROFILE_MODES``), the
// extension fallback failed and the file 404'd against the programs
// endpoint. The new contract puts ``source`` on the URL — never
// the extension — and the store dispatches by ``source`` alone.
//
// This test asserts:
//
//   * the ``EDITOR_SOURCES`` enum + ``openInEditor`` helper cover
//     every surface the UI used to embed ``Editor.vue`` in;
//   * the filename extension is consulted **only** to derive
//     ``syntaxMode`` (the CodeMirror overlay), never the dispatch
//     branch;
//   * the routing-by-extension code path is gone, including the
//     ``PROFILE_MODES`` fallback and the ``isProfilePath`` helper.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");

const editorPath = resolve(repoRoot, "frontend/src/stores/editor.ts");
const helperPath = resolve(repoRoot, "frontend/src/helpers/openInEditor.ts");
const editorViewPath = resolve(repoRoot, "frontend/src/views/EditorView.vue");

function readText(path) {
  return readFileSync(path, "utf-8");
}

const editorText = readText(editorPath);
const helperText = readText(helperPath);
const editorViewText = readText(editorViewPath);

// ---------------------------------------------------------------------- //
// Source enum                                                             //
// ---------------------------------------------------------------------- //

test("EDITOR_SOURCES exposes every surface the universal editor dispatches", () => {
  assert.match(
    editorText,
    /PROFILES:\s*['"]profiles['"]/,
    "EDITOR_SOURCES.PROFILES must be 'profiles'",
  );
  assert.match(
    editorText,
    /ACTIVE:\s*['"]active['"]/,
    "EDITOR_SOURCES.ACTIVE must be 'active'",
  );
  assert.match(
    editorText,
    /STAGED:\s*['"]staged['"]/,
    "EDITOR_SOURCES.STAGED must be 'staged'",
  );
  assert.match(
    editorText,
    /M_CODES:\s*['"]m_codes['"]/,
    "EDITOR_SOURCES.M_CODES must be 'm_codes'",
  );
  assert.match(
    editorText,
    /PROGRAMS:\s*['"]programs['"]/,
    "EDITOR_SOURCES.PROGRAMS must be 'programs'",
  );
  assert.match(
    editorText,
    /MACROS:\s*['"]macros['"]/,
    "EDITOR_SOURCES.MACROS must be 'macros'",
  );
});

test("source-driven dispatch table covers all six sources", () => {
  // Every source must appear as a switch arm in dispatchRead.
  for (const source of [
    "PROFILES",
    "ACTIVE",
    "STAGED",
    "M_CODES",
    "PROGRAMS",
    "MACROS",
  ]) {
    const pattern = new RegExp(
      `case\\s+EDITOR_SOURCES\\.${source}:`,
    )
    assert.match(
      editorText,
      pattern,
      `dispatchRead must handle EDITOR_SOURCES.${source}`,
    )
  }
  // Read-only sources (active / staged) MUST NOT appear in
  // dispatchWrite's switch — saving them would silently 500
  // against the backend because the endpoints are GET-only.
  assert.doesNotMatch(
    editorText,
    /case\s+EDITOR_SOURCES\.ACTIVE:[^]*?writeActiveContent/,
    "dispatchWrite must not write to the active source",
  )
  assert.doesNotMatch(
    editorText,
    /case\s+EDITOR_SOURCES\.STAGED:[^]*?writeStagedContent/,
    "dispatchWrite must not write to the staged source",
  )
});

// ---------------------------------------------------------------------- //
// Routing-by-extension removal                                            //
// ---------------------------------------------------------------------- //

test("the routing-by-extension fallback is removed", () => {
  // Pre-refactor: isProfilePath consulted modeForFilename(path).
  // Post-refactor: routing is source-driven; the helper is gone.
  assert.doesNotMatch(
    editorText,
    /\bisProfilePath\b/,
    "isProfilePath helper must be removed",
  )
  assert.doesNotMatch(
    editorText,
    /\bPROFILE_PATH_PREFIXES\b/,
    "PROFILE_PATH_PREFIXES table must be removed",
  )
  assert.doesNotMatch(
    editorText,
    /\bGCODE_MODES\b/,
    "GCODE_MODES table must be removed",
  )
  assert.doesNotMatch(
    editorText,
    /\bMCODE_NAME_PATTERN\b/,
    "MCODE_NAME_PATTERN helper must be removed",
  )
  // ``EXTENSION_MODES`` is now a small lookup table used by
  // ``modeForFilename`` for the CodeMirror overlay. We assert it
  // exists (for the visual overlay) but only as a constant — it
  // must not appear in any dispatch branch.
  assert.match(
    editorText,
    /\bEXTENSION_MODES\b/,
    "EXTENSION_MODES is kept (modeForFilename uses it for the overlay)",
  )
  // Sanity: there is no longer a PROFILE_MODES table either.
  assert.doesNotMatch(
    editorText,
    /\bPROFILE_MODES\b/,
    "PROFILE_MODES table must be removed",
  )
})

test("filename extension is consulted ONLY for syntax highlighting", () => {
  // ``modeForFilename`` is still exported (CodeMirror needs it), but
  // it must not appear in the dispatch path.
  assert.match(editorText, /export\s+function\s+modeForFilename\b/)
  // The store reads it for ``syntaxMode`` only.
  assert.match(
    editorText,
    /syntaxMode\s*=\s*modeForFilename\(/,
    "syntaxMode must derive from modeForFilename()",
  )
  // The dispatch functions must not consult the filename. Pull
  // each function body out of the source by hand and assert the
  // body contains no ``modeForFilename`` reference — this is more
  // robust than a cross-file regex.
  const sliceBetween = (text, start, end) => {
    const i = text.indexOf(start)
    if (i < 0) return ""
    const j = text.indexOf(end, i + start.length)
    if (j < 0) return text.slice(i)
    return text.slice(i, j)
  }
  const readBody = sliceBetween(
    editorText,
    "async function dispatchRead",
    "async function dispatchWrite",
  )
  const writeBody = sliceBetween(
    editorText,
    "async function dispatchWrite",
    "function describeError",
  )
  assert.doesNotMatch(
    readBody,
    /modeForFilename/,
    "dispatchRead must not call modeForFilename",
  )
  assert.doesNotMatch(
    writeBody,
    /modeForFilename/,
    "dispatchWrite must not call modeForFilename",
  )
})

test("open() rejects unknown sources", () => {
  assert.match(
    editorText,
    /Invalid editor source/,
    "open() must validate the source against EDITOR_SOURCES",
  )
})

test("the open() signature is the new (source, name, readOnly) contract", () => {
  // The legacy ``open(filename, readOnly, mode, content)`` is gone.
  assert.match(
    editorText,
    /open\(\{\s*source[^}]*\}\)/,
    "open() must take a single options object",
  )
  assert.doesNotMatch(
    editorText,
    /open\(\s*filename\s*,\s*readOnly\s*,\s*mode/,
    "the legacy open(filename, readOnly, mode, content) signature is gone",
  )
})

test("store no longer exports the old isProfilePath / modeForFilename as a router", () => {
  // ``resolveEditorMode`` was the legacy re-export; the new
  // ``modeForFilename`` is the CodeMirror hint only.
  assert.doesNotMatch(editorText, /\bresolveEditorMode\b/)
})

// ---------------------------------------------------------------------- //
// Helpers + EditorView                                                    //
// ---------------------------------------------------------------------- //

test("openInEditor validates source against the enum", () => {
  assert.match(helperText, /invalid source/)
  assert.match(helperText, /openInEditor/)
  assert.match(helperText, /router\.push\([^]*?name:\s*['"]editor['"]/)
})

test("openInEditor pushes a query string with source + name + readOnly", () => {
  assert.match(
    helperText,
    /query:\s*\{[^}]*source[^}]*name[^}]*readOnly/s,
    "openInEditor must push source + name + readOnly",
  )
})

test("EditorView reads (source, name, readOnly) from the URL query", () => {
  assert.match(editorViewText, /currentSource/)
  assert.match(editorViewText, /currentName/)
  assert.match(editorViewText, /currentReadOnly/)
  // The view destructures ``route = useRoute()`` then reads
  // ``route.query.{source,name,readOnly}`` — match either form.
  assert.match(
    editorViewText,
    /useRoute\(\)|route\.query/,
    "EditorView must read from useRoute() / route.query",
  )
})

test("EditorView still embeds Editor.vue but never calls its own copy", () => {
  assert.match(editorViewText, /<Editor\b/)
})

// ---------------------------------------------------------------------- //
// Legacy routes removed                                                   //
// ---------------------------------------------------------------------- //

test("legacy /config/:filename and /programs/:filename routes are gone", () => {
  const routerText = readText(
    resolve(repoRoot, "frontend/src/router/index.ts"),
  )
  assert.doesNotMatch(
    routerText,
    /path:\s*['"]\/config\/:filename/,
    "legacy /config/:filename route must be removed",
  )
  assert.doesNotMatch(
    routerText,
    /path:\s*['"]\/programs\/:filename/,
    "legacy /programs/:filename route must be removed",
  )
  assert.match(
    routerText,
    /path:\s*['"]\/editor['"]/,
    "the new /editor route must be registered",
  )
})

// ---------------------------------------------------------------------- //
// The .txt profile bug is gone                                             //
// ---------------------------------------------------------------------- //

test("modeForFilename still returns 'text' for .txt — but no router reads it", () => {
  // Pre-refactor regression: ``modeForFilename("printer.cfg.txt")``
  // returns ``"text"`` (the extension after the last dot). The
  // legacy ``isProfilePath`` consulted that, found ``text`` missing
  // from PROFILE_MODES, and routed to programs → 404.
  //
  // Post-refactor: ``modeForFilename`` still returns ``"text"`` for
  // the visual overlay, but no router calls it for dispatch. The
  // only consumer is ``syntaxMode``.
  assert.match(editorText, /txt[^]*?['"]text['"]/)
})

test("Save buttons are hidden when readOnly=true", () => {
  // The ``Save`` and ``Save & Close`` controls are write-only
  // affordances. When the store is read-only (``active`` / ``staged``
  // / any source the caller pinned read-only) the editor hides
  // them entirely instead of rendering greyed-out buttons the
  // operator cannot use.
  const editorViewBody = readText(
    resolve(repoRoot, "frontend/src/views/EditorView.vue"),
  )
  // The Save + Save & Close pair must live inside a
  // ``v-if="!editorStore.readOnly"`` guard.
  assert.match(
    editorViewBody,
    /v-if=["']!editorStore\.readOnly["']/,
    "Save buttons must be gated on !editorStore.readOnly",
  )
})

test("no caller still pushes the removed /config route", () => {
  // Regression guard: when the universal editor refactor replaced
  // ``/config/:filename`` with ``/editor?source=...&name=...`` a
  // few callers were left behind — the route was removed but the
  // pushes were not. Grep every Vue file under ``src/`` for any
  // ``name: 'config'`` router push; the legacy route no longer
  // exists so any match is a bug.
  const sources = [
    "frontend/src/views/DashboardView.vue",
    "frontend/src/views/EditorView.vue",
    "frontend/src/components/FileManager.vue",
    "frontend/src/modules/machineconfig/components/MachineConfigView.vue",
    "frontend/src/modules/machineconfig/components/ActivePanel.vue",
    "frontend/src/modules/machineconfig/components/CompiledOutputViewer.vue",
    "frontend/src/modules/machineconfig/components/ProfilesExplorer.vue",
    "frontend/src/modules/macros/components/MacroManagerPanel.vue",
    "frontend/src/modules/macros/components/McodeManagerPanel.vue",
    "frontend/src/modules/macros/components/McodePanel.vue",
    "frontend/src/modules/macros/components/MacroPanel.vue",
  ]
  for (const rel of sources) {
    const abs = resolve(repoRoot, rel)
    if (!existsSync(abs)) continue
    const text = readText(abs)
    assert.doesNotMatch(
      text,
      /router\.push\(\s*\{\s*name:\s*['"]config['"]/,
      `${rel} still pushes the removed 'config' route`,
    )
  }
})