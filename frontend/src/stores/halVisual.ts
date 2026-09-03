// Visual HAL editor store.
//
// Owns the pin/signal world state fetched from `GET /api/v1/hal/layout`
// plus the in-session signal wiring the operator builds with
// drag-and-drop. This feature is completely independent from the
// text-based configuration editor: nothing here reads or writes
// editor documents.
//
// Validation rules (enforced centrally in `connectPin`, so every
// call site — drop handler, future context menu, tests — shares
// them):
//
// * Type matching — once a signal's type is locked (by its first
//   connected pin, or by the backend for existing signals), only
//   pins of the same HAL type may join it.
// * Arity — a signal has at most ONE source (OUT / writer pin)
//   but any number of targets (IN / reader pins).
// * A pin may appear in a signal only once (either side).
//
// Signal edits are frontend-only for now: drafts are marked
// `isDraft` and nothing is POSTed back. `fetchLayout()` resets to
// the backend truth.

import { defineStore, storeToRefs } from "pinia";
import { computed, ref, type Ref } from "vue";

import HalVisualService from "../facades/halFacade";
import type { HalPinResource } from "../../generated/api/models/HalPinResource";
import type { HalSignalResource } from "../../generated/api/models/HalSignalResource";

/** Local, editable signal block (backend signals + in-session drafts). */
export interface VisualSignal {
    /** Stable in-session key (`sig:<name>` for backend rows, `draft:<n>` for new ones). */
    id: string;
    name: string;
    /** HAL type token; ``""`` while the signal is still untyped. */
    type: string;
    source: HalPinResource | null;
    targets: HalPinResource[];
    description: string;
    /** True when the block was created in this session (not from the backend). */
    isDraft: boolean;
}

/** Result contract for validation-guarded mutations. */
export interface ConnectResult {
    ok: boolean;
    message?: string;
}

const OK: ConnectResult = { ok: true };

function fail(message: string): ConnectResult {
    return { ok: false, message };
}

export const useHalVisualStore = defineStore("halVisual", () => {
    // --- reactive state ---------------------------------------------- //
    const inPins: Ref<HalPinResource[]> = ref([]);
    const outPins: Ref<HalPinResource[]> = ref([]);
    const signals: Ref<VisualSignal[]> = ref([]);
    const loading = ref(false);
    const error = ref("");

    // --- non-reactive counters ---------------------------------------- //
    let draftCounter = 0;

    // --- fetch --------------------------------------------------------- //

    async function fetchLayout(): Promise<boolean> {
        loading.value = true;
        error.value = "";
        try {
            const layout = await HalVisualService.fetchLayout();
            if (!layout) {
                error.value = "Failed to load HAL layout from the backend.";
                return false;
            }
            inPins.value = layout.in_pins ?? [];
            outPins.value = layout.out_pins ?? [];
            signals.value = (layout.signals ?? []).map((s: HalSignalResource) => ({
                id: `sig:${s.name}`,
                name: s.name,
                type: s.type ?? "bit",
                source: s.source ?? null,
                targets: s.targets ?? [],
                description: s.description ?? "",
                isDraft: false,
            }));
            return true;
        } finally {
            loading.value = false;
        }
    }

    // --- signal lifecycle ---------------------------------------------- //

    function createSignal(name?: string, type: string = ""): VisualSignal | null {
        const trimmed = (name ?? "").trim();
        const finalName = trimmed || `signal-${signals.value.length + 1}`;
        if (signals.value.some((s) => s.name === finalName)) {
            return null;
        }
        const signal: VisualSignal = {
            id: `draft:${++draftCounter}`,
            name: finalName,
            // Empty string means "auto" — the type is adopted from the
            // first connected pin. A pre-set type is enforced by
            // ``connectPin``'s type-matching rule from the first drop on.
            type: type,
            source: null,
            targets: [],
            description: "",
            isDraft: true,
        };
        signals.value = [...signals.value, signal];
        return signal;
    }

    function removeSignal(signalId: string): void {
        signals.value = signals.value.filter((s) => s.id !== signalId);
    }

    // --- validation-guarded wiring -------------------------------------- //

    function connectPin(signalId: string, pin: HalPinResource): ConnectResult {
        const signal = signals.value.find((s) => s.id === signalId);
        if (!signal) {
            return fail("Signal block no longer exists.");
        }

        // A pin may only appear once on either side of a signal.
        if (signal.source?.id === pin.id || signal.targets.some((t) => t.id === pin.id)) {
            return fail(`Pin '${pin.full_name}' is already connected to signal '${signal.name}'.`);
        }

        // Type matching: once the signal carries a type, reject foreign types.
        if (signal.type !== "" && pin.type !== signal.type) {
            return fail(
                `Type mismatch: cannot connect ${pin.type} pin '${pin.full_name}' ` +
                    `to ${signal.type} signal '${signal.name}'.`,
            );
        }

        if (pin.direction === "out") {
            // Arity: exactly one source (writer) per signal.
            if (signal.source !== null) {
                return fail(
                    `Signal '${signal.name}' already has a source ` +
                        `('${signal.source.full_name}'). A signal can only have one OUT pin — ` +
                        `remove it first.`,
                );
            }
            signal.source = pin;
        } else {
            signal.targets = [...signal.targets, pin];
        }

        // First connected pin locks the signal's type.
        if (signal.type === "") {
            signal.type = pin.type;
        }
        return OK;
    }

    function removeSource(signalId: string): void {
        const signal = signals.value.find((s) => s.id === signalId);
        if (signal) {
            signal.source = null;
            // An emptied signal becomes typeless again.
            if (signal.targets.length === 0) {
                signal.type = "";
            } else {
                signal.type = signal.targets[0].type;
            }
        }
    }

    function removeTarget(signalId: string, pinId: string): void {
        const signal = signals.value.find((s) => s.id === signalId);
        if (!signal) return;
        signal.targets = signal.targets.filter((t) => t.id !== pinId);
        // Re-derive the type from whatever remains connected.
        if (signal.source) {
            signal.type = signal.source.type;
        } else if (signal.targets.length > 0) {
            signal.type = signal.targets[0].type;
        } else {
            signal.type = "";
        }
    }

    // --- getters --------------------------------------------------------- //

    const pinById = computed<ReadonlyMap<string, HalPinResource>>(() => {
        const map = new Map<string, HalPinResource>();
        for (const pin of [...inPins.value, ...outPins.value]) {
            map.set(pin.id, pin);
        }
        return map;
    });

    return {
        inPins,
        outPins,
        signals,
        loading,
        error,
        fetchLayout,
        createSignal,
        removeSignal,
        connectPin,
        removeSource,
        removeTarget,
        pinById,
    };
});

export function useHalVisualRefs() {
    const store = useHalVisualStore();
    return { store, ...storeToRefs(store) };
}

export default useHalVisualStore;
