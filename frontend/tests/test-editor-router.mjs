// Regression test for the universal-editor path router.
//
// Run with: node --test frontend/tests/test-editor-router.mjs
//
// ``stores/editor.js::isProfilePath`` (and the ``routeByPath`` that
// wraps it) used to require an explicit ``machine_config/`` or
// ``profiles/`` prefix. A URL like ``/config/klipper.cfg`` (the bare
// filename operators type most often) lost the prefix and fell
// through to the programs endpoint, which 404'd. The fix adds an
// extension-based fallback that catches every path whose mode
// implies a known profile kind (``cfg`` / ``ini`` / ``conf`` /
// ``toml`` / ``profile``).
//
// Source-text checks guard the structure of the fix. The end-to-end
// shape (path → service call) is verified by the broader
// ``test-machineconfig-registry.mjs`` test, the Vite production
// build, and the live ``GET /api/v1/modules/machineconfig/profiles/content``
// round-trip in the manual smoke check.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");

const editorPath = resolve(repoRoot, "frontend/src/stores/editor.js");

function readText(path) {
  return readFileSync(path, "utf-8");
}

test("isProfilePath exposes the prefix-based primary path", () => {
  const text = readText(editorPath);
  // Prefix membership table is intact.
  assert.match(
    text,
    /const\s+PROFILE_PATH_PREFIXES\s*=\s*\[\s*['"]machine_config\/['"]\s*,\s*['"]profiles\/['"]\s*\]/,
  );
  // modeForFilename is the function the new fallback delegates to.
  assert.match(text, /export\s+function\s+modeForFilename\b/);
});

test("isProfilePath falls back to the extension when no prefix is present", () => {
  const text = readText(editorPath);
  // The new branch must consult the extension-derived mode and check
  // membership in PROFILE_MODES so a bare filename like
  // ``klipper.cfg`` stops falling through to the programs endpoint.
  assert.match(
    text,
    /PROFILE_MODES\.has\(\s*modeForFilename\(\s*path\s*\)\s*\)/,
  );
});

test("PROFILE_MODES still maps every profile-known extension", () => {
  const text = readText(editorPath);
  // The set of profile modes must cover ``config``, ``profile``,
  // ``ini``, ``cfg``, ``conf`` — those modes are the ones the
  // extension fallback uses to short-circuit routing.
  const expected = ["config", "profile", "ini", "cfg", "conf"];
  // Each token must appear inside the Set literal.
  for (const mode of expected) {
    assert.match(
      text,
      new RegExp(`PROFILE_MODES\\s*=[^]*['"]${mode}['"]`),
      `PROFILE_MODES must include ${mode}`,
    );
  }
});

test("EXTENSION_MODES includes every extension the prefix-fallback relies on", () => {
  const text = readText(editorPath);
  // For a bare path like ``klipper.cfg`` to route to profile,
  // ``modeForFilename`` must return ``"config"`` (a member of
  // PROFILE_MODES). Verify the four profile-relevant extensions are
  // wired through EXTENSION_MODES.
  for (const ext of ["cfg", "ini", "conf", "toml"]) {
    assert.match(
      text,
      new RegExp(`\\b${ext}:\\s*['"]config['"]`),
      `EXTENSION_MODES must map .${ext} to 'config'`,
    );
  }
});

test("GCODE_MODES keeps gcode / ngc / nc off the profile path", () => {
  const text = readText(editorPath);
  assert.match(text, /GCODE_MODES\s*=\s*new\s+Set\(\s*\[\s*['"]gcode['"]\s*,\s*['"]ngc['"]\s*,\s*['"]nc['"]\s*\]\s*\)/);
});

test("routeByPath still defers to isProfilePath", () => {
  const text = readText(editorPath);
  // Single point of decision: every readByPath / writeByPath call
  // routes through ``routeByPath``, which itself defers to
  // ``isProfilePath``. The fix is therefore replayed by every I/O
  // path without further touch-ups.
  assert.match(text, /function\s+routeByPath\(\s*path\s*\)\s*\{[\s\S]*isProfilePath/);
  assert.match(text, /readByPath[\s\S]*routeByPath/);
  assert.match(text, /writeByPath[\s\S]*routeByPath/);
});

test("architecture comment documents the bare-path fallback", () => {
  const text = readText(editorPath);
  // The Path → service table inside the architecture comment must
  // mention the extension-based fallback so a future maintainer
  // understands why ``/config/klipper.cfg`` lands on the profiles
  // endpoint rather than 404ing.
  assert.match(text, /Bare paths whose extension maps to a known profile mode/);
  assert.match(text, /klipper\.cfg/);
});
