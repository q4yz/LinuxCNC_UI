// Tests for the four shared UI primitives in ``frontend/src/ui/``.
//
// Each test asserts the public contract — the variant / event /
// prop names the rest of the codebase depends on. Behavioural tests
// live in components themselves (the runtime events / focus order
// / transitions are verified by the manual QA matrix in
// ``ui/README.md``).

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");

const buttonPath = resolve(repoRoot, "frontend/src/ui/Button.vue");
const iconPath = resolve(repoRoot, "frontend/src/ui/Icon.vue");
const drawerPath = resolve(repoRoot, "frontend/src/ui/Drawer.vue");
const confirmPath = resolve(repoRoot, "frontend/src/ui/Confirm.vue");
const indexPath = resolve(repoRoot, "frontend/src/ui/index.js");

function read(path) {
  return readFileSync(path, "utf-8");
}

const button = read(buttonPath);
const icon = read(iconPath);
const drawer = read(drawerPath);
const confirm = read(confirmPath);
const index = read(indexPath);

// ---------------------------------------------------------------- //
// Button.vue                                                            //
// ---------------------------------------------------------------- //

test("Button exposes the documented variants and sizes", () => {
  // Five variants, three sizes, and a ``loading`` spinner are
  // the contract. Adding a variant requires a new entry in
  // ``VARIANT_CLASSES``; the test asserts the contract so
  // reviewers notice when one goes missing.
  for (const v of ["primary", "success", "danger", "secondary", "ghost"]) {
    assert.match(button, new RegExp(`\\b${v}:\\s*['"]`), `missing variant ${v}`);
  }
  for (const s of ["sm", "md", "lg"]) {
    assert.match(button, new RegExp(`\\b${s}:\\s*['"]`), `missing size ${s}`);
  }
  // Loading spinner markup — a rounded circle border with
  // ``animate-spin``. The class list is what consumers rely on.
  assert.match(button, /animate-spin/);
  assert.match(button, /aria-busy=/);
  // Forwards the native ``type`` attribute and ``disabled`` flag.
  assert.match(button, /:type="type"/);
  assert.match(button, /:disabled="disabled \|\| loading"/);
  // Two slots — ``icon`` (left) and the default slot (right).
  assert.match(button, /<slot\s+name="icon"\s*\/>/);
  assert.match(button, /<slot\s*\/>/);
});

test("Button defaults are stable", () => {
  // The default variant is ``primary`` so a one-off
  // ``<Button>Save</Button>`` always renders the dashboard's
  // primary blue without the consumer having to specify it.
  assert.match(button, /variant:\s*\{\s*type:\s*String,\s*default:\s*"primary"/);
  assert.match(button, /size:\s*\{\s*type:\s*String,\s*default:\s*"md"/);
  // Loading defaults to ``false`` — the spinner is opt-in so the
  // common button render is just a plain button.
  assert.match(button, /loading:\s*\{\s*type:\s*Boolean,\s*default:\s*false/);
  // Native button type defaults to ``button`` so a stray
  // ``<Button>`` inside a form does not accidentally submit.
  assert.match(button, /type:\s*\{\s*type:\s*String,\s*default:\s*"button"/);
});

// ---------------------------------------------------------------- //
// Icon.vue                                                             //
// ---------------------------------------------------------------- //

test("Icon ships the icon set documented in the file", () => {
  // The set is small and operator-facing. Add a new icon by
  // appending a row to the ``ICONS`` object; the test fails if a
  // row's name slips past review.
  const required = [
    "close",
    "edit",
    "delete",
    "save",
    "refresh",
    "plus",
    "alert",
    "info",
    "check",
    "chevronDown",
    "chevronLeft",
    "warning",
    "plusCircle",
  ];
  for (const name of required) {
    assert.match(icon, new RegExp(`\\b${name}:\\s*\\{`), `missing icon ${name}`);
  }
  // All icons share the 24x24 viewBox so they render at the same
  // scale regardless of which one is selected.
  assert.match(icon, /viewBox="0 0 24 24"/);
  // Default size matches the inline icons in
  // ``AppSidebar.vue:28-30`` (``h-4 w-4`` = 16×16).
  assert.match(icon, /size:\s*\{\s*type:\s*String,\s*default:\s*"h-4 w-4"/);
  // Decorative (the common case) keeps aria-hidden; ``label=true``
  // opt-in exposes ``aria-label`` for the rare screen-reader-only
  // icon.
  assert.match(icon, /aria-hidden="true"/);
  assert.match(icon, /aria-label="label \? icon\.label : null"/);
});

test("Icon unknown-name renders an empty placeholder, not a fallback", () => {
  // A missing icon name should not silently render an arbitrary
  // fallback that the operator could misread as something
  // meaningful. The component renders an empty ``<svg>`` with the
  // requested size so layouts don't shift.
  assert.match(icon, /v-else/);
});

// ---------------------------------------------------------------- //
// Drawer.vue                                                           //
// ---------------------------------------------------------------- //

test("Drawer exposes the v-model + slide lifecycle", () => {
  // ``v-model:open`` is the public contract; ``update:open`` and
  // ``close`` are the emitted events.
  assert.match(drawer, /open:\s*\{\s*type:\s*Boolean,\s*default:\s*false/);
  assert.match(drawer, /defineEmits\(\[\s*"update:open",\s*"close"\s*\]\)/);
  // Right is the canonical anchor — the toast container moved to
  // the bottom-right corner to avoid the same overlap risk the
  // top-right drawer used to cause. The drawer keeps its right-
  // side default.
  assert.match(drawer, /side:\s*\{\s*type:\s*String,\s*default:\s*"right"/);
  // Teleporter renders the drawer at the document body so a
  // parent with ``overflow: hidden`` cannot clip it.
  assert.match(drawer, /<Teleport to="body">/);
  // Backdrop click and Escape both close.
  assert.match(drawer, /@click="onBackdropClick"/);
  assert.match(drawer, /event\.key === "Escape"/);
  // Header slot + body slot. Body scrolls inside the drawer so
  // a long list does not push the header off the viewport.
  assert.match(drawer, /<slot name="header"\s*\/>/);
  assert.match(drawer, /flex-1 overflow-y-auto/);
});

test("Drawer disallows non-anchor sides at prop-validation time", () => {
  // The router only ships ``right`` and ``left``; ``top`` /
  // ``bottom`` are reserved for future expansion. The validator
  // constrains caller mistakes at prop-check time.
  assert.match(
    drawer,
    /validator:\s*\(s\)\s*=>\s*\["right",\s*"left"\]\.includes\(s\)/,
  );
});

// ---------------------------------------------------------------- //
// Confirm.vue                                                         //
// ---------------------------------------------------------------- //

test("Confirm emits both confirm and cancel distinctly", () => {
  // Treat ``confirm`` and ``cancel`` as separate paths so the
  // host does not silently perform the destructive action on
  // dismiss. The component emits ``update:open`` (two-way bind),
  // ``confirm`` (operator accepted), and ``cancel`` (operator
  // dismissed).
  assert.match(confirm, /defineEmits\(\[\s*"update:open",\s*"confirm",\s*"cancel"\s*\]\)/);
  // Both buttons emit through the same component-level handlers
  // but the emitted event differs — never ``confirm`` from the
  // reject button and vice versa.
  assert.match(confirm, /emit\("confirm"\)/);
  assert.match(confirm, /emit\("cancel"\)/);
});

test("Confirm supports three button variants", () => {
  // ``primary`` / ``success`` / ``danger`` cover every confirm
  // action in the dashboards. ``secondary`` is the default reject
  // styling. Reusing ``Button.vue`` here means every visual change
  // to buttons propagates to modals automatically.
  for (const v of ["primary", "success", "danger"]) {
    assert.match(
      confirm,
      new RegExp(`${v}`),
      `missing variant ${v}`,
    );
  }
  // ``rejectButtonStyle`` defaults to ``secondary`` — the muted
  // outlined button matches every dashboard panel.
  assert.match(confirm, /rejectButtonStyle[\s\S]*?default:\s*"secondary"/);
});

test("Confirm locks body scroll while open", () => {
  // The modal can be taller than the viewport when the operator's
  // browser is short; locking body scroll while the modal is open
  // keeps the backdrop covering the page.
  assert.match(confirm, /document\.body\.style\.overflow/);
});

test("Confirm is keyboard-friendly", () => {
  // ``Escape`` dismisses, ``Enter`` confirms. ``Shift+Enter`` is
  // intentionally not bound so a multi-line operator message does
  // not accidentally trigger confirm on newline.
  assert.match(confirm, /event\.key === "Escape"/);
  assert.match(confirm, /event\.key === "Enter"/);
  assert.match(confirm, /!event\.shiftKey/);
});

test("Confirm reuses Button + Icon primitives", () => {
  // The whole point of the shared UI layer is that Confirm
  // composes Button + Icon rather than re-implementing the styling.
  // Asserting the imports here is the regression guard.
  assert.match(confirm, /import Icon from "\.\/Icon\.vue"/);
  assert.match(confirm, /import Button from "\.\/Button\.vue"/);
  // Uses ``<Icon name="close">`` for the dismiss cross.
  assert.match(confirm, /<Icon name="close"/);
});

// ---------------------------------------------------------------- //
// ui/index.js barrel                                                  //
// ---------------------------------------------------------------- //

test("ui/index.js exports the four primitives", () => {
  // A future contributor adding a primitive to ``ui/`` should
  // also re-export it here so consumers import from one place.
  for (const name of ["Button", "Icon", "Drawer", "Confirm"]) {
    assert.match(index, new RegExp(`export\\s+\\{\\s*default\\s+as\\s+${name}`));
  }
});
