// Central UI settings core: BaseSetting + registry + facade, against a
// stubbed generated ``SettingsService`` (the real facade code runs).

import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { resolve, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const mod = (p: string) => import(pathToFileURL(resolve(here, p)).href);

const { createPinia, setActivePinia } = await import("pinia");
const { shallowReactive } = await import("vue");
const { SettingsService } = await mod("../generated/api/services/SettingsService.ts");
const { settingsRegistry, CheckboxSetting, NumberSetting, SelectSetting, TextSetting } = await mod("../src/settings/index.ts");
const { useConsoleStore } = await mod("../src/stores/console.ts");

// --- fake backend --------------------------------------------------------
let stored: Record<string, unknown> = {};
let failWrites = false;
let listCalls = 0;
const apiError = (status: number) => Object.assign(new Error(`HTTP ${status}`), { status });

SettingsService.listSettings = async () => {
  listCalls += 1;
  return { values: { ...stored } };
};
SettingsService.readSetting = async (key: string) => {
  if (!(key in stored)) throw apiError(404);
  return { key, value: stored[key] };
};
SettingsService.writeSetting = async (key: string, body: { value: unknown }) => {
  if (failWrites) throw apiError(500);
  stored[key] = body.value;
  return { key, value: body.value };
};
SettingsService.resetSetting = async (key: string) => {
  delete stored[key];
};

beforeEach(() => {
  setActivePinia(createPinia());
  settingsRegistry._resetForTests();
  stored = {};
  failWrites = false;
  listCalls = 0;
});

const logs = () => useConsoleStore().messages.map((m: { type: string; text: string }) => `${m.type}:${m.text}`);

// --- value semantics -----------------------------------------------------

test("a setting shows its default until a stored value arrives", async () => {
  stored = { "machine.estop_disables_power": true };
  const s = new CheckboxSetting("Machine", "Power off on E-Stop", "machine.estop_disables_power", false);
  assert.equal(s.value, false);
  assert.equal(s.isLoaded, false);

  assert.equal(await settingsRegistry.fetchAll(), true);
  assert.equal(s.value, true);
  assert.equal(s.isLoaded, true);
  assert.equal(s.isStored, true);
});

test("fetchAll is one request per session", async () => {
  new CheckboxSetting("Machine", "A", "machine.a", false);
  await settingsRegistry.fetchAll();
  await settingsRegistry.fetchAll();
  assert.equal(listCalls, 1);
});

test("a setting registered after the fetch hydrates from the cache", async () => {
  stored = { "temperature.unit": "kelvin" };
  await settingsRegistry.fetchAll();
  const late = new SelectSetting("Temperature", "Unit", "temperature.unit", "celsius", [
    { value: "celsius", label: "°C" },
    { value: "kelvin", label: "K" },
  ]);
  assert.equal(late.value, "kelvin");
});

test("a critical setting is never taken from the cache and is null until a fresh load", async () => {
  stored = { "camera.ip_camera_url": "http://cam/stream" };
  const url = new TextSetting("Camera", "IP camera URL", "camera.ip_camera_url", "", {}, { critical: true });
  await settingsRegistry.fetchAll();
  assert.equal(url.value, null);

  stored["camera.ip_camera_url"] = "http://cam-2/stream"; // changed by someone else
  assert.equal(await url.load(), true);
  assert.equal(url.value, "http://cam-2/stream");
});

test("a critical setting that was never stored loads as its default", async () => {
  const id = new TextSetting("Camera", "Default device", "camera.default_device_id", "", {}, { critical: true });
  await id.load();
  assert.equal(id.value, "");
  assert.equal(id.isStored, false);
});

test("an invalid stored value falls back to the default with a warning", async () => {
  stored = { "machine.default_jog_velocity": "fast" };
  const v = new NumberSetting("Machine", "Default jog velocity", "machine.default_jog_velocity", 20, { min: 1 });
  await settingsRegistry.fetchAll();
  assert.equal(v.value, 20);
  assert.ok(logs().some((l: string) => l.startsWith("warning:") && l.includes("machine.default_jog_velocity")));
});

// --- save / reset --------------------------------------------------------

test("save adopts the backend echo", async () => {
  const s = new CheckboxSetting("Machine", "A", "machine.a", false);
  const result = await s.save(true);
  assert.equal(result.ok, true);
  assert.equal(s.value, true);
  assert.deepEqual(stored, { "machine.a": true });
});

test("a failed save keeps the old value and reports the failure", async () => {
  const s = new CheckboxSetting("Machine", "A", "machine.a", false);
  failWrites = true;
  const result = await s.save(true);
  assert.equal(result.failed, true);
  assert.equal(s.value, false);
  assert.ok(logs().some((l: string) => l.startsWith("error:")));
});

test("an invalid value is never sent", async () => {
  const v = new NumberSetting("Machine", "V", "machine.v", 20, { min: 1, max: 100 });
  const result = await v.save(500);
  assert.equal(result.failed, true);
  assert.deepEqual(stored, {});
});

test("reset returns to the default", async () => {
  const s = new CheckboxSetting("Machine", "A", "machine.a", false);
  await s.save(true);
  await s.reset();
  assert.equal(s.value, false);
  assert.equal(s.isStored, false);
  assert.deepEqual(stored, {});
});

// --- registry rules ------------------------------------------------------

test("an identical re-definition (HMR) is tolerated, a different one throws", () => {
  new CheckboxSetting("Machine", "A", "machine.a", false);
  assert.doesNotThrow(() => new CheckboxSetting("Machine", "A", "machine.a", false));
  assert.throws(() => new CheckboxSetting("Machine", "A", "machine.a", true), /defined twice/);
  assert.throws(
    () => new SelectSetting("Machine", "A", "machine.a", "x", [{ value: "x", label: "X" }]),
    /defined twice/,
  );
});

test("type config is part of the definition (subclass fields would be missing at register time)", () => {
  new NumberSetting("Machine", "V", "machine.v", 20, { min: 1, max: 100 });
  assert.throws(() => new NumberSetting("Machine", "V", "machine.v", 20, { min: 1, max: 200 }), /defined twice/);
});

test("settings are grouped by category for the Settings view", () => {
  new CheckboxSetting("Machine", "B", "machine.b", false);
  new CheckboxSetting("Machine", "A", "machine.a", false);
  new CheckboxSetting("Camera", "C", "camera.c", false);
  const groups = settingsRegistry.categories.value;
  assert.deepEqual(Object.keys(groups).sort(), ["Camera", "Machine"]);
  assert.deepEqual(groups.Machine.map((s: { label: string }) => s.label), ["A", "B"]);
});

test("value still works when the instance is reached through a reactive container", async () => {
  // Regression for the markRaw rule: a reactive proxy would unwrap the
  // inner ref and make ``.value`` undefined.
  const s = new CheckboxSetting("Machine", "A", "machine.a", false);
  const box = shallowReactive({ list: [s] });
  const viaReactive = (await import("vue")).reactive({ s });
  await s.save(true);
  assert.equal(box.list[0].value, true);
  assert.equal(viaReactive.s.value, true);
});
