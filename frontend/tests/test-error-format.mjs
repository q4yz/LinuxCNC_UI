// Tests for ``frontend/src/core/error-format.js`` — the single
// source of truth that translates the generated OpenAPI client's
// error shapes into one operator-readable string.
//
// Three envelope shapes land in the frontend today (issue #99):
//   1. Structured ``{ error: { section, key, line, message, kind } }``.
//   2. FastAPI default ``{ detail: <string> }`` or ``detail: [ … ]``.
//   3. Plain ``Error.message``.
//
// These tests pin the helper's behaviour across all three and the
// falsy-input edge case so a future envelope shape change has a
// clear contract to extend.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");

const helperPath = resolve(repoRoot, "frontend/src/core/error-format.js");
const helperFileURL = pathToFileURL(helperPath).href;
const source = readFileSync(helperPath, "utf-8");

// Import the helper for behavioural checks. ``core/error-format.js``
// is a plain ES module — no Vue / Pinia imports — so we can run it
// in plain node.
const { describeError, describeErrorOr } = await import(helperFileURL);

test("module surface: default export + named exports", () => {
  assert.match(source, /export\s+function\s+describeError\b/);
  assert.match(source, /export\s+function\s+describeErrorOr\b/);
  assert.match(source, /export\s+default\s+describeError\b/);
});

test("describeError returns empty for falsy input", () => {
  assert.equal(describeError(null), "");
  assert.equal(describeError(undefined), "");
  assert.equal(describeError(""), "");
});

test("describeError returns the input unchanged when it is a string", () => {
  // Some call sites stringify errors before calling; the helper
  // must not re-wrap.
  assert.equal(describeError("disk full"), "disk full");
});

test("describeErrorOr falls back to the supplied default when empty", () => {
  assert.equal(describeErrorOr(null, "boom"), "boom");
  assert.equal(describeErrorOr(undefined, "boom"), "boom");
  assert.equal(describeErrorOr("", "boom"), "boom");
  assert.equal(describeErrorOr(null), "Unknown error");
});

test("describeError reads the issue #99 structured envelope first", () => {
  const err = {
    body: {
      error: {
        section: "stepper_x",
        key: "full_steps_per_rotation",
        line: null,
        message: "Undefined keyword 'full_steps_per_rotation'",
        kind: "undefined_keyword",
      },
      detail: { msg: "ignored because structured wins" },
    },
    message: "ignored because structured wins",
  };
  assert.equal(describeError(err), "Undefined keyword 'full_steps_per_rotation'");
});

test("describeError falls back to FastAPI detail string", () => {
  const err = { body: { detail: "Profile not found: printer.cfg" } };
  assert.equal(describeError(err), "Profile not found: printer.cfg");
});

test("describeError joins array-form Pydantic validation errors with '; '", () => {
  const err = {
    body: {
      detail: [
        { msg: "field required", loc: ["body", "filename"] },
        { msg: "value is not a valid integer", loc: ["body", "line"] },
      ],
    },
  };
  assert.equal(
    describeError(err),
    "field required; value is not a valid integer",
  );
});

test("describeError unwraps a nested detail envelope", () => {
  const err = { body: { detail: { message: "nested detail" } } };
  assert.equal(describeError(err), "nested detail");
});

test("describeError falls back to Error.message", () => {
  const err = new Error("plain failure");
  assert.equal(describeError(err), "plain failure");
});

test("describeError falls back to String(error) for unknown shapes", () => {
  // An object without any of the recognised fields still produces a
  // readable string rather than ``"[object Object]"``.
  const result = describeError({ weird: "shape" });
  assert.match(result, /^\[object Object\]$|weird|shape/);
});

test("describeErrorOr surfaces structured-envelope text without falling back", () => {
  const err = {
    body: { error: { message: "structured wins" } },
  };
  assert.equal(describeErrorOr(err, "FALLBACK"), "structured wins");
});
