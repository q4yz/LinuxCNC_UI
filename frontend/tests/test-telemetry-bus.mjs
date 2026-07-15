// Tests for the TelemetryBus by-reference contract.
//
// Run with: node --test frontend/tests/test-telemetry-bus.mjs

import { test } from "node:test";
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const url = pathToFileURL(
  resolve(here, "../src/core/modules/telemetry-bus.js"),
).href;

const { TelemetryBus } = await import(url);

test("TelemetryBus delivers the same reference to every subscriber", () => {
  const bus = new TelemetryBus();
  const received = [];

  bus.subscribe("t", (topic, payload) => received.push(payload));
  bus.subscribe("t", (topic, payload) => received.push(payload));

  const sample = { v: 1 };
  bus.publish("t", sample);

  assert.equal(received.length, 2);
  // TelemetryBus passes by reference — the two subscribers receive the
  // exact same object the publisher handed to ``publish``.
  assert.strictEqual(received[0], sample);
  assert.strictEqual(received[1], sample);
});

test("TelemetryBus: one bad subscriber doesn't block others", () => {
  const bus = new TelemetryBus();
  const delivered = [];

  bus.subscribe("t", () => {
    throw new Error("boom");
  });
  bus.subscribe("t", (topic, payload) => delivered.push(payload));

  // Should not throw — the bus swallows the first subscriber's error.
  bus.publish("t", { v: 1 });
  assert.deepEqual(delivered, [{ v: 1 }]);
});