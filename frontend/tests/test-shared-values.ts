// #128: a slider moved on one client follows on every other client.
// The machine backend relays ``ui_value`` over the telemetry socket;
// these pin the client side of that contract.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = resolve(here, "../src");
const read = (p: string) => readFileSync(resolve(src, p), "utf-8");

test("the facade applies ui_values / ui_value frames and publishes ui_value", () => {
  const facade = read("facades/servoThreadFacade.ts");
  assert.match(facade, /case 'ui_values':[\s\S]*?replaceAll\(/);
  assert.match(facade, /case 'ui_value':[\s\S]*?\.apply\(key, value\)/);
  assert.match(facade, /publishSharedValue\(key: string, value: SharedValue\)[\s\S]*?type: 'ui_value', key, value/);
});

test("useSharedValue follows received values and publishes on commit", () => {
  const composable = read("composables/useSharedValue.ts");
  assert.match(composable, /watch\(shared,[\s\S]*?local\.value = next/);
  assert.match(composable, /store\.publish\(toValue\(key\), toShared\(local\.value\)\)/);
  // the facade is the transport behind the store
  assert.match(read("facades/servoThreadFacade.ts"), /setSharedValueSender\(\(key, value\) => servoThreadFacade\.publishSharedValue\(key, value\)\)/);
});

test("jog speed, extruder speed/distance are shared; the analog spindle follows set_speed", () => {
  const jog = read("components/machine/JogControls.vue");
  assert.match(jog, /useSharedValue\('jog\.speed', sharedJogSpeed\)/);
  assert.match(jog, /publishJogSpeed\(\)/);
  const extruder = read("components/tools/ExtruderCard.vue");
  assert.match(extruder, /`extruder\.\$\{props\.tool\.id\}\.speed`/);
  assert.match(extruder, /`extruder\.\$\{props\.tool\.id\}\.distance`/);
  assert.match(extruder, /@change="publishSpeed\(\)"/);
  assert.match(extruder, /@change="publishDistance\(\)"/);
  const analog = read("components/tools/AnalogSpindleCard.vue");
  assert.match(analog, /watch\(\(\) => props\.tool\?\.set_speed/);
});

test("runtime: a received value lands in the local ref, publish sends it", async () => {
  (globalThis as any).window ??= globalThis;
  const { pathToFileURL } = await import("node:url");
  const mod = (p: string) => pathToFileURL(resolve(src, p)).href;
  const { createPinia, setActivePinia } = await import("pinia");
  const { ref, nextTick } = await import("vue");
  setActivePinia(createPinia());
  const { useSharedValue } = await import(mod("composables/useSharedValue.ts"));
  const { useSharedValuesStore, setSharedValueSender } = await import(mod("stores/sharedValues.ts"));

  const sent: object[] = [];
  setSharedValueSender((key: string, value: unknown) => sent.push({ key, value }));

  const local = ref(300);
  const { publish } = useSharedValue("extruder.e0.speed", local);
  const store = useSharedValuesStore();

  // another client's value (the backend's ui_value frame)
  store.apply("extruder.e0.speed", 450);
  await nextTick();
  assert.equal(local.value, 450);
  // a non-number is ignored by the default accept
  store.apply("extruder.e0.speed", "fast");
  await nextTick();
  assert.equal(local.value, 450);

  local.value = 600;
  publish();
  assert.deepEqual(sent, [{ key: "extruder.e0.speed", value: 600 }]);
  assert.equal(store.values["extruder.e0.speed"], 600);
});
