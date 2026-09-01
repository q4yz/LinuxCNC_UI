// Visual HAL editor store — behavioural tests for the drag-and-drop
// wiring rules.
//
// Run with: npm test (node --test via the repo's test script)
//
// The store's `connectPin` action is the single chokepoint for the
// editor's two hard rules, so these tests execute the real store
// (fresh Pinia per test) rather than asserting on source text:
//
//   * Type matching — a signal locks to the HAL type of its first
//     connected pin; foreign-type drops are rejected with a
//     "Type mismatch" message the view surfaces as a toast.
//   * Arity — exactly one source (OUT) per signal, any number of
//     targets (IN).
//   * A pin may appear only once in a signal (either side).
//   * Disconnects re-derive the signal type from what remains.

import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { createPinia, setActivePinia } from "pinia";

import { useHalVisualStore } from "../src/stores/halVisual";
import type { HalPinResource } from "../generated/api/models/HalPinResource";

function pin(id: string, direction: "in" | "out", type: string): HalPinResource {
    return {
        id,
        full_name: id,
        direction,
        type,
        component_name: id.split(".")[0] ?? "",
        pin_name: id.split(".")[1] ?? "",
        description: "",
    };
}

const OUT_FLOAT = pin("motion.speed-out", "out", "float");
const OUT_FLOAT_B = pin("motion.speed-out-2", "out", "float");
const OUT_BIT = pin("motion.spindle-on", "out", "bit");
const IN_FLOAT_A = pin("drive.speed-fb", "in", "float");
const IN_FLOAT_B = pin("drive.speed-fb2", "in", "float");
const IN_BIT = pin("motion.spindle-on-fb", "in", "bit");

beforeEach(() => {
    setActivePinia(createPinia());
});

function freshSignal() {
    const store = useHalVisualStore();
    const signal = store.createSignal("test-sig");
    assert.ok(signal, "createSignal must succeed for a unique name");
    return { store, signal };
}

test("createSignal adds an empty, untyped draft block", () => {
    const { store } = freshSignal();
    assert.equal(store.signals.length, 1);
    const draft = store.signals[0];
    assert.equal(draft.isDraft, true);
    assert.equal(draft.type, "");
    assert.equal(draft.source, null);
    assert.deepEqual(draft.targets, []);
});

test("createSignal rejects duplicate names", () => {
    const { store } = freshSignal();
    assert.equal(store.createSignal("test-sig"), null);
    assert.equal(store.signals.length, 1);
});

test("createSignal auto-names empty input", () => {
    const store = useHalVisualStore();
    const created = store.createSignal("   ");
    assert.ok(created);
    assert.notEqual(created!.name.trim(), "");
});

test("an OUT pin becomes the single source and locks the signal type", () => {
    const { store, signal } = freshSignal();
    const result = store.connectPin(signal.id, OUT_FLOAT);
    assert.deepEqual(result, { ok: true });
    assert.equal(store.signals[0].source?.id, OUT_FLOAT.id);
    assert.equal(store.signals[0].type, "float");
});

test("arity: a second OUT pin is rejected", () => {
    const { store, signal } = freshSignal();
    assert.equal(store.connectPin(signal.id, OUT_FLOAT).ok, true);
    // Same type so ONLY the arity rule can fire.
    const second = store.connectPin(signal.id, OUT_FLOAT_B);
    assert.equal(second.ok, false);
    assert.match(second.message ?? "", /already has a source/);
    // Source must still be the first pin.
    assert.equal(store.signals[0].source?.id, OUT_FLOAT.id);
});

test("arity: multiple IN targets are allowed", () => {
    const { store, signal } = freshSignal();
    assert.equal(store.connectPin(signal.id, OUT_FLOAT).ok, true);
    assert.equal(store.connectPin(signal.id, IN_FLOAT_A).ok, true);
    const third = store.connectPin(signal.id, IN_FLOAT_B);
    assert.deepEqual(third, { ok: true });
    assert.deepEqual(
        store.signals[0].targets.map((t) => t.id),
        [IN_FLOAT_A.id, IN_FLOAT_B.id],
    );
});

test("type matching: float pin cannot join a bit signal", () => {
    const { store, signal } = freshSignal();
    assert.equal(store.connectPin(signal.id, OUT_BIT).ok, true);
    const mismatch = store.connectPin(signal.id, IN_FLOAT_A);
    assert.equal(mismatch.ok, false);
    assert.match(mismatch.message ?? "", /Type mismatch: cannot connect float pin .* to bit signal/);
    assert.equal(store.signals[0].targets.length, 0);
});

test("type matching applies to the source slot too", () => {
    const { store, signal } = freshSignal();
    assert.equal(store.connectPin(signal.id, IN_BIT).ok, true);
    const mismatch = store.connectPin(signal.id, OUT_FLOAT);
    assert.equal(mismatch.ok, false);
    assert.match(mismatch.message ?? "", /Type mismatch/);
    assert.equal(store.signals[0].source, null);
});

test("an untyped signal adopts the first connected pin's type", () => {
    const { store, signal } = freshSignal();
    // Target first — no source yet.
    assert.equal(store.connectPin(signal.id, IN_FLOAT_A).ok, true);
    assert.equal(store.signals[0].type, "float");
    // Now a matching-typed source is fine, a bit source is not.
    assert.equal(store.connectPin(signal.id, OUT_FLOAT).ok, true);
    assert.equal(store.connectPin(signal.id, OUT_BIT).ok, false);
});

test("a pin may appear only once in a signal (either side)", () => {
    const { store, signal } = freshSignal();
    assert.equal(store.connectPin(signal.id, OUT_FLOAT).ok, true);
    const dupAsTarget = store.connectPin(signal.id, {
        ...OUT_FLOAT,
        direction: "in",
    });
    assert.equal(dupAsTarget.ok, false);
    assert.match(dupAsTarget.message ?? "", /already connected/);
});

test("duplicate targets are rejected", () => {
    const { store, signal } = freshSignal();
    assert.equal(store.connectPin(signal.id, OUT_FLOAT).ok, true);
    assert.equal(store.connectPin(signal.id, IN_FLOAT_A).ok, true);
    const dup = store.connectPin(signal.id, IN_FLOAT_A);
    assert.equal(dup.ok, false);
    assert.match(dup.message ?? "", /already connected/);
    assert.equal(store.signals[0].targets.length, 1);
});

test("removeSource clears the slot and re-derives the type", () => {
    const { store, signal } = freshSignal();
    store.connectPin(signal.id, OUT_FLOAT);
    store.connectPin(signal.id, IN_FLOAT_A);
    store.removeSource(signal.id);
    assert.equal(store.signals[0].source, null);
    // Type survives via the remaining target.
    assert.equal(store.signals[0].type, "float");
});

test("removeTarget re-derives the type; empty signal becomes untyped", () => {
    const { store, signal } = freshSignal();
    store.connectPin(signal.id, IN_BIT); // locks bit
    store.removeTarget(signal.id, IN_BIT.id);
    assert.equal(store.signals[0].targets.length, 0);
    assert.equal(store.signals[0].type, "");
});

test("removeSignal drops the block entirely", () => {
    const { store, signal } = freshSignal();
    store.removeSignal(signal.id);
    assert.equal(store.signals.length, 0);
    const gone = store.connectPin(signal.id, OUT_FLOAT);
    assert.equal(gone.ok, false);
    assert.match(gone.message ?? "", /no longer exists/);
});
