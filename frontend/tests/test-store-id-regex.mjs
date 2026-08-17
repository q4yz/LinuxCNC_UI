// Tests for the Pinia store-id regex lint check.
//
// The check is implemented as a pure-Node CLI script
// (frontend/scripts/check-store-ids.mjs). These tests validate that
// the regex matches the documented contract:
//
//   * ``defineStore('camera', ...)`` fails the lint.
//   * ``defineStore('module_camera', ...)`` passes.
//
// Run with: node --test frontend/tests/test-store-id-regex.mjs

import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");
const scriptPath = resolve(repoRoot, "frontend/scripts/check-store-ids.mjs");

function runLint(targetDir) {
  try {
    const stdout = execFileSync("node", [scriptPath, targetDir], {
      encoding: "utf-8",
    });
    return { code: 0, stdout, stderr: "" };
  } catch (err) {
    return {
      code: err.status ?? 1,
      stdout: err.stdout?.toString() ?? "",
      stderr: err.stderr?.toString() ?? "",
    };
  }
}

test("defineStore('camera', ...) fails the lint", () => {
  const dir = mkdtempSync(join(tmpdir(), "lint-"));
  try {
    writeFileSync(
      join(dir, "index.ts"),
      "import { defineStore } from 'pinia';\n" +
        "export const s = defineStore('camera', { state: () => ({}) });\n",
    );
    const result = runLint(dir);
    assert.notEqual(result.code, 0, "expected non-zero exit on bad id");
    assert.match(
      result.stdout + result.stderr,
      /Store id must match.*\^module_/,
    );
    assert.match(result.stdout + result.stderr, /'camera'/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("defineStore('module_camera', ...) passes the lint", () => {
  const dir = mkdtempSync(join(tmpdir(), "lint-"));
  try {
    writeFileSync(
      join(dir, "index.ts"),
      "import { defineStore } from 'pinia';\n" +
        "export const s = defineStore('module_camera', { state: () => ({}) });\n",
    );
    const result = runLint(dir);
    assert.equal(result.code, 0, `expected zero exit, got ${result.code}`);
    assert.match(result.stdout, /OK/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("empty directory passes the lint", () => {
  const dir = mkdtempSync(join(tmpdir(), "lint-"));
  try {
    const result = runLint(dir);
    assert.equal(result.code, 0);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});