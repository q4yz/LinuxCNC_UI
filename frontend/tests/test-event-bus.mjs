// Tests for the frontend core/modules/event-bus.js EventBus.
//
// Run with: node --test frontend/tests/test-event-bus.mjs
//
// These tests cover the contract guarantees documented in
// MODULE_SYSTEM_ROADMAP.md § 12 Gotcha #3:
//
//   * Every subscriber receives a frozen copy of the payload.
//   * A subscriber mutating its copy cannot affect another subscriber.
//
// We import the JS file via a dynamic import with a file:// URL so the
// test runner doesn't need ESM configuration beyond the default.

import { test } from "node:test";
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const eventBusUrl = pathToFileURL(
  resolve(here, "../src/core/modules/event-bus.js"),
).href;

const { EventBus } = await import(eventBusUrl);

test("subscribers receive deep-frozen payload copies", () => {
  const bus = new EventBus();
  const delivered = [];

  bus.subscribe("t", (topic, payload) => {
    delivered.push(payload);
  });
  bus.subscribe("t", (topic, payload) => {
    delivered.push(payload);
  });

  bus.publish("t", { a: 1, nested: { b: 2 } });

  assert.equal(delivered.length, 2);
  // Frozen — mutating the copy must throw (strict mode only).
  assert.ok(Object.isFrozen(delivered[0]));
  assert.ok(Object.isFrozen(delivered[0].nested));

  // Two distinct objects, not the same reference.
  assert.notStrictEqual(delivered[0], delivered[1]);
});

test("mutation in one subscriber does not affect another", () => {
  const bus = new EventBus();
  const seen = [];

  bus.subscribe("t", (topic, payload) => {
    // Mutating a frozen payload throws in strict mode (ES modules are
    // strict by default). The bus catches the throw and the *second*
    // subscriber still receives the original, unchanged value.
    try {
      payload.a = "MUTATED";
    } catch (_) {
      // expected — frozen copy
    }
    seen.push(["evil", payload.a]);
  });
  bus.subscribe("t", (topic, payload) => {
    seen.push(["benign", payload.a]);
  });

  bus.publish("t", { a: "original" });

  assert.deepEqual(seen, [
    ["evil", "original"], // frozen; mutation threw
    ["benign", "original"],
  ]);
});

test("subscribe / unsubscribe roundtrip", () => {
  const bus = new EventBus();
  const cb = () => {};
  bus.subscribe("t", cb);
  assert.equal(bus.unsubscribe("t", cb), true);
  assert.equal(bus.unsubscribe("t", cb), false);
});

test("topics() reflects current subscriptions", () => {
  const bus = new EventBus();
  bus.subscribe("a", () => {});
  bus.subscribe("b", () => {});
  assert.deepEqual(bus.topics().sort(), ["a", "b"]);
});