// ``(MSG, ...)`` vs ``(ABORT, ...)`` from a macro.
//
// Both arrive over LinuxCNC's error channel, but only ``ABORT`` is a
// fault. The backend stamps ``severity`` on every entry; these tests
// pin how ``core/linuxcnc-errors.ts`` reads it, and that
// ``servoThreadFacade.ts`` routes an ``info`` entry to an info toast
// instead of an error.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");

const { formatLinuxCNCError, isLinuxCNCError, isLinuxCNCMessage, lookupLinuxCNCError } = await import(
  pathToFileURL(resolve(repoRoot, "frontend/src/core/linuxcnc-errors.ts")).href
);

test("an operator message (MSG) is recognised and printed as plain text", () => {
  const msg = { kind: 13, text: "Bore Diameter is: 20.012", severity: "info" };
  assert.equal(isLinuxCNCMessage(msg), true);
  assert.equal(formatLinuxCNCError(msg), "Bore Diameter is: 20.012");
});

test("an ABORT stays an error with its kind label", () => {
  const abort = { kind: 11, text: "Error: Slow probe missed target!", severity: "error" };
  assert.equal(isLinuxCNCMessage(abort), false);
  assert.equal(formatLinuxCNCError(abort), "[Operator error #11] Error: Slow probe missed target!");
});

test("a payload without severity (older backend) is treated as an error", () => {
  assert.equal(isLinuxCNCMessage({ kind: 13, text: "x" }), false);
});

test("the kind table uses real python-linuxcnc values", () => {
  // 13 used to be labelled "Coolant error" — it is OPERATOR_DISPLAY.
  assert.equal(lookupLinuxCNCError(11).name, "Operator error");
  assert.equal(lookupLinuxCNCError(13).name, "Operator message");
  assert.equal(lookupLinuxCNCError(1).name, "NML error");
});

test("the type guard accepts severity and rejects garbage", () => {
  assert.equal(isLinuxCNCError({ kind: 13, text: "x", severity: "info" }), true);
  assert.equal(isLinuxCNCError({ kind: 13, text: "x", severity: "loud" }), false);
});

test("servoThreadFacade routes info entries to an info toast", () => {
  const source = readFileSync(resolve(repoRoot, "frontend/src/facades/servoThreadFacade.ts"), "utf-8");
  assert.match(source, /isLinuxCNCMessage\(payload\)\)\s*{\s*consoleStore\.info\(message, \{ popup: true \}\)/);
  // Both the live envelope and the history replay go through it.
  assert.equal((source.match(/surfaceLinuxCNCEntry\(consoleStore/g) ?? []).length, 2);
});
