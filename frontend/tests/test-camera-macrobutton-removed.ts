// Regression guard: the camera page never calls the old per-module
// ``useMacroButtonConfig("camera")`` again.
//
// That built ``/api/v1/modules/camera/settings/macroButtons``, a key the
// camera router never owned — it answered 404 on every mount, burning
// one of the browser's 6 HTTP/1.1 connection slots (the "all pending"
// freeze). Camera macro buttons now come from the central
// ``machine.macro_buttons`` UI setting (slots ``camera.1``–``camera.3``,
// see test-macro-button.ts), loaded once at app start.
//
// Run with: ``node --test frontend/tests/test-camera-macrobutton-removed.ts``

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");
const cameraDir = resolve(repoRoot, "frontend/src/components/camera");
const read = (rel) => readFileSync(resolve(cameraDir, rel), "utf-8");

test("CameraViewer does not feed the camera module into useMacroButtonConfig", () => {
  const text = read("CameraViewer.vue");
  assert.doesNotMatch(
    text,
    /useMacroButtonConfig/,
    "CameraViewer must not call the old per-module useMacroButtonConfig",
  );
  // Its buttons read the central setting instead (loaded once at app start).
  assert.match(text, /macroButtons\.bySlot/);
});

test("CameraSettings does not feed the camera module into useMacroButtonConfig", () => {
  const text = read("CameraSettings.vue");
  assert.doesNotMatch(
    text,
    /useMacroButtonConfig/,
    "CameraSettings must not call useMacroButtonConfig until the backend CameraSettings model adds a macroButtons field",
  );
  assert.doesNotMatch(
    text,
    /<MacroButtonEditor\b/,
    "CameraSettings must not render a MacroButtonEditor (no key to bind to)",
  );
});
