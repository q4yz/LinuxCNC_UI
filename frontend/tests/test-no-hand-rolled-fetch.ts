// Dedicated lint: no domain store may hand-roll HTTP with a raw
// ``fetch()`` call instead of going through the generated OpenAPI
// client. See ``.agent/context/LESSONS_LEARNED.md`` § 2.7 — a
// domain store once shipped with its own ``postJson``/``fetch``
// helpers for every backend route, so a backend field rename
// silently broke the hand-written call while the generated client
// (which tracks the OpenAPI schema via ``npm run generate-api``)
// would have caught it at compile time.
//
// Scope is exactly ``frontend/src/stores/*.ts`` (non-recursive, and
// every file in the directory rather than a hardcoded list, so a
// brand-new store is covered automatically) because that is the
// tripwire's documented boundary: the one sanctioned exception,
// ``core/settings/createModuleSettings.ts``, lives outside
// ``stores/`` entirely, and infrastructure-level probes
// (``composables/useMachineOnline.ts``'s reachability check) and
// facades bridging a not-yet-regenerated client
// (``facades/machineLifecycleFacade.ts``, see its own file header)
// are a different, already-documented category — not a domain store
// hand-rolling business-data HTTP.
//
// Run with: ``node --test frontend/tests/test-no-hand-rolled-fetch.ts``

import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { resolve, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");
const storesDir = resolve(repoRoot, "frontend/src/stores");

function storeFiles(): string[] {
  return readdirSync(storesDir)
    .filter((name) => name.endsWith(".ts"))
    .filter((name) => statSync(join(storesDir, name)).isFile());
}

test("no domain store hand-rolls fetch() instead of the generated client", () => {
  const files = storeFiles();
  // Guard the guard: if the directory listing ever comes back empty
  // (a bad path, a repo layout change) this test must fail loudly
  // rather than silently passing with nothing checked.
  assert.ok(files.length > 0, "expected to find store files under frontend/src/stores");

  const offenders: string[] = [];
  for (const name of files) {
    const text = readFileSync(join(storesDir, name), "utf-8");
    if (/\bfetch\(/.test(text)) {
      offenders.push(name);
    }
  }

  assert.deepEqual(
    offenders,
    [],
    `store(s) hand-roll fetch() instead of the generated OpenAPI client: ${offenders.join(", ")} — ` +
      "see .agent/context/LESSONS_LEARNED.md § 2.7",
  );
});
