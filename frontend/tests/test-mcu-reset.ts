// MCU reset — static ``mcus`` from the base-thread snapshot drive a
// RESET MCU button that POSTs ``/api/v1/modules/mcu/reset``.
//
// Behavioural checks on the mapper/entity; source checks on the
// store/facade/component wiring (same style as test-servo-thread.ts).

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");
const src = (p: string) => resolve(repoRoot, "frontend/src", p);
const read = (p: string) => readFileSync(src(p), "utf-8");

const { toMcuMap, toSnapshot } = await import(pathToFileURL(src("mappers/baseThreadMapper.ts")).href);

test("static mcus map into McuState entities keyed by id", () => {
  const mcus = toMcuMap({
    mcu: { id: "mcu", connection: "remora-spi", resettable: true },
    pp: { id: "pp", connection: "parallelport", resettable: false },
    bad: { connection: "remora-spi" }, // no id -> dropped
  });
  assert.deepEqual(Object.keys(mcus), ["mcu", "pp"]);
  assert.equal(mcus.mcu.resettable, true);
  assert.equal(mcus.mcu.connection, "remora-spi");
  assert.equal(mcus.pp.resettable, false);
});

test("resettable is only true for a literal true (base tier sends null)", () => {
  assert.equal(toMcuMap({ m: { id: "m", resettable: null } }).m.resettable, false);
  assert.equal(toMcuMap({ m: { id: "m", resettable: "yes" } }).m.resettable, false);
});

test("a snapshot without mcus yields an empty map", () => {
  assert.deepEqual(toSnapshot({}).mcus, {});
});

test("the base-thread store loads mcus with the static tier, not the 1 Hz poll", () => {
  const store = read("stores/baseThread.ts");
  assert.match(store, /fetchStatic\(\);\s*axes\.value = snapshot\.axes;\s*mcus\.value = snapshot\.mcus;/);
  assert.doesNotMatch(store.slice(store.indexOf("async function refresh"), store.indexOf("async function fetchStaticAxes")), /mcus\.value/);
  assert.match(store, /hasResettableMcu = computed\(\(\) => Object\.values\(mcus\.value\)\.some\(\(m\) => m\.resettable\)\)/);
});

test("reset goes facade -> generated client and back through reportCommandFailure", () => {
  assert.match(read("facades/mcuFacade.ts"), /ModulesMcuService\.resetMcus\(\)/);
  const machine = read("stores/machine.ts");
  assert.match(machine, /async function resetMcus\(\)[\s\S]*?mcuFacade\.resetMcus\(\)[\s\S]*?reportCommandFailure\("reset MCU", result\)/);
});

test("the RESET MCU button only renders when a resettable MCU exists", () => {
  const view = read("components/machine/PowerOn.vue");
  assert.match(view, /v-if="hasResettableMcu"\s*@click="store\.resetMcus\(\)"/);
});
