// Regression guard: the camera module never gains ``macroButtons``
// support until the ``CameraSettings`` Pydantic model adds the field.
//
// The previous version of ``CameraViewer.vue`` and ``CameraSettings.vue``
// called ``useMacroButtonConfig("camera")`` which builds
// ``/api/v1/modules/camera/settings/macroButtons``. The camera router
// does not own a ``macroButtons`` key — the call landed on the
// generic ``/settings/{key}`` endpoint and answered 404 every time
// the camera page mounted, burning one of the browser's 6 HTTP/1.1
// connection slots for nothing and contributing to the "all
// pending" freeze reported on the box. The composable's home is
// the ``axis`` (Machine) module — see ``MachineSettingsPanel.vue``,
// ``DroPanel.vue``, ``NgcCoordinateSystemViewer.vue``.
//
// Re-enable the camera calls once ``CameraSettings`` in the
// backend models gains a ``macroButtons: list[...] = []`` field.
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
    "CameraViewer must not call useMacroButtonConfig until the backend CameraSettings model adds a macroButtons field",
  );
  assert.doesNotMatch(
    text,
    /<MacroButton\b/,
    "CameraViewer must not render a MacroButton (it depends on the camera-keyed macroButtons slot)",
  );
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
