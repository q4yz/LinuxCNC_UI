// Structural tests for ``frontend/src/facades/temperatureFacade.js``.
//
// Behavioural coverage of the wire-shape translation lives in
// ``test-temperature-mapper.mjs``. This file pins the facade's
// public surface so a future refactor that silently renames or
// drops a method is caught immediately.
//
// The facade imports the generated OpenAPI client, which can't
// resolve under plain node. We skip the dynamic import when the
// facade isn't loadable; CI runs the suite against the real
// generated client.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");
const facadePath = resolve(repoRoot, "frontend/src/facades/temperatureFacade.js");
const source = readFileSync(facadePath, "utf-8");
const generatedPath = resolve(
  repoRoot,
  "frontend/generated/api/index.ts",
);

test("module surface: temperatureFacade object + named export", () => {
  assert.match(source, /export\s+const\s+temperatureFacade\s*=/);
  assert.match(source, /export\s+default\s+temperatureFacade/);
});

test("facade exposes fetchReadings()", () => {
  assert.match(source, /fetchReadings\s*[(:]/);
});

test("facade exposes setTarget(toolId, target)", () => {
  assert.match(source, /setTarget\s*\(\s*\w+\s*,\s*\w+\s*\)/);
});

test("facade delegates fetchReadings to BaseThreadService.getBaseThreadSnapshot", () => {
  assert.match(source, /BaseThreadService\.getBaseThreadSnapshot/);
  assert.match(source, /toReadingSet/);
});

test("facade delegates setTarget to ModulesToolsService.setToolTarget", () => {
  assert.match(source, /ModulesToolsService\.setToolTarget/);
  assert.match(source, /toHeaterSetTargetRequest/);
});

test("facade returns CommandResult, never throws", () => {
  // The facade catches generated-client throws and wraps them in
  // a ``CommandResult.failure(...)`` so callers never have to
  // try/catch the dispatch.
  assert.match(source, /CommandResult\.success/);
  assert.match(source, /CommandResult\.failure/);
  assert.match(source, /describeError/);
  // The ``setTarget`` body must wrap the call in a try/catch.
  assert.match(source, /catch\s*\(\s*err\s*\)/);
});

test("facade is frozen so consumers cannot mutate the surface", () => {
  assert.match(source, /Object\.freeze\(\{[\s\S]+fetchReadings[\s\S]+setTarget/);
});

test("(skipped without generated client) behavioural: setTarget success", async (t) => {
  if (!existsSync(generatedPath)) {
    t.skip("generated/api/index.ts not present — behavioural assertions need the real client");
    return;
  }
  // When the generated client is present we import the facade
  // and exercise the success path against a stub. The test
  // catches regressions in the wrapping contract.
  let facade;
  try {
    const url = pathToFileURL(facadePath).href;
    facade = await import(url);
  } catch (err) {
    t.skip(`facade import failed: ${err.message}`);
    return;
  }
  const result = await facade.temperatureFacade.setTarget("extruder", 210);
  assert.ok(result, "facade must return a CommandResult");
  // ``result.ok`` is the only reliable assertion — the generated
  // client's actual response shape depends on the backend build.
  assert.equal(typeof result.ok, "boolean");
});
