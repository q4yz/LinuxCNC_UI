// Installing any release (pre-releases, older ones: going back) from the
// update card.
//
// Run with: ``node --test frontend/tests/test-update-versions.ts``

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import { compareRelease, versionParts } from "../src/components/releaseOrder";

const src = resolve(dirname(fileURLToPath(import.meta.url)), "../src");
const read = (rel: string) => readFileSync(resolve(src, rel), "utf-8");

test("release order: numeric, a pre-release before its release", () => {
  assert.deepEqual(versionParts("v1.2.10"), [1, 2, 10]);
  assert.equal(versionParts("abc"), null);
  assert.equal(compareRelease("v1.0.0", "v1.1.0"), -1, "older: going back");
  assert.equal(compareRelease("v1.10.0", "v1.9.0"), 1, "numeric, not string");
  assert.equal(compareRelease("v1.1.0", "v1.1.0"), 0);
  assert.equal(compareRelease("v1.2.0-rc1", "v1.2.0"), -1);
  assert.equal(compareRelease("v1.2.0", "v1.2.0-rc1"), 1);
  assert.equal(compareRelease("v1.0.0", null), null);
});

test("the facade lists releases and sends the chosen tag", () => {
  const facade = read("facades/systemFacade.ts");
  assert.match(facade, /SystemService\.listReleases\(\)/);
  assert.match(facade, /triggerSystemUpdate\(\{ mode, tag: mode === "release" \? tag \?\? null : null \}\)/);
  assert.match(read("stores/systemUpdate.ts"), /systemFacade\.triggerUpdate\(updateMode, tag\)/);
});

test("the update card picks any installable release and warns when going back", () => {
  const card = read("components/UpdateManager.vue");
  assert.match(card, /v-for="release in releases\?\.releases \?\? \[\]"[\s\S]*?:disabled="!release\.installable"/);
  assert.match(card, /updateStore\.start\('release', tag\)/);
  assert.match(card, /order === -1 \? `Go back to the older release/);
});
