<script setup lang="ts">
// Visual HAL editor — a standalone three-column graphical wiring board.
//
// Left column: every available IN pin (reader). Right column: every
// OUT pin (writer). Middle column: the signals ("wires") — blocks
// that own exactly one source OUT pin and any number of target IN
// pins. Operators drag pins from the palettes onto a signal card;
// the store's `connectPin` enforces type matching and arity, and a
// rejected drop surfaces as a toast plus a shake/red-ring flash on
// the signal card.
//
// Built on the shared ui primitives (BaseButton / BaseCard /
// BaseInput / BaseSelect) so the editor shares the dashboard's
// visual language.
//
// This view is completely independent from the text-based editor:
// it never imports editor stores, documents, or routers.

import { computed, onMounted, ref } from "vue";

import { BaseButton, Icon } from "../ui/index.ts";
import BaseCard from "../ui/BaseCard.vue";
import BaseInput from "../ui/BaseInput.vue";
import BaseSelect from "../ui/BaseSelect.vue";
import { useToast } from "../core/toast";
import { useHalVisualStore, type VisualSignal } from "../stores/halVisual";
import type { HalPinResource } from "../../generated/api/models/HalPinResource";

const store = useHalVisualStore();
const toast = useToast();

// Custom drag-and-drop MIME type so drop zones can distinguish HAL
// pin payloads from any other draggable content on the page.
const PIN_MIME = "application/x-hal-pin";

// --- local UI state --------------------------------------------------- //

const newSignalName = ref("");
// "" = auto: the signal adopts the type of its first connected pin.
const newSignalType = ref("");
const draggingPinId = ref<string | null>(null);
const dragOverSignalId = ref<string | null>(null);
const rejectedSignalId = ref<string | null>(null);
let rejectTimer: ReturnType<typeof setTimeout> | null = null;

// --- drag payload ------------------------------------------------------ //

function onPinDragStart(event: DragEvent, pin: HalPinResource) {
    if (!event.dataTransfer) return;
    event.dataTransfer.setData(PIN_MIME, JSON.stringify(pin));
    // text/plain fallback so the payload survives stricter drop targets.
    event.dataTransfer.setData("text/plain", pin.full_name);
    event.dataTransfer.effectAllowed = "copy";
    draggingPinId.value = pin.id;
}

function onPinDragEnd() {
    draggingPinId.value = null;
}

// --- drop handling ------------------------------------------------------ //

function onSignalDragOver(event: DragEvent, signal: VisualSignal) {
    if (!event.dataTransfer) return;
    if (!event.dataTransfer.types.includes(PIN_MIME)) return;
    // Required so the browser allows the drop.
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    dragOverSignalId.value = signal.id;
}

function onSignalDragLeave(signal: VisualSignal) {
    if (dragOverSignalId.value === signal.id) {
        dragOverSignalId.value = null;
    }
}

function parsePinPayload(event: DragEvent): HalPinResource | null {
    const raw = event.dataTransfer?.getData(PIN_MIME);
    if (!raw) return null;
    try {
        const parsed = JSON.parse(raw) as HalPinResource;
        return parsed && typeof parsed.id === "string" ? parsed : null;
    } catch {
        return null;
    }
}

function onSignalDrop(event: DragEvent, signal: VisualSignal) {
    event.preventDefault();
    dragOverSignalId.value = null;

    const pin = parsePinPayload(event);
    if (!pin) {
        toast.warn("Drop ignored: could not read the dragged pin.");
        return;
    }

    const result = store.connectPin(signal.id, pin);
    if (!result.ok) {
        // Visual rejection: flash the card red and shake it.
        flashReject(signal.id);
        toast.error(result.message ?? "Connection rejected.");
    }
}

function flashReject(signalId: string) {
    rejectedSignalId.value = signalId;
    if (rejectTimer !== null) {
        clearTimeout(rejectTimer);
    }
    rejectTimer = setTimeout(() => {
        rejectedSignalId.value = null;
        rejectTimer = null;
    }, 500);
}

// --- signal lifecycle --------------------------------------------------- //

function addSignal() {
    const created = store.createSignal(newSignalName.value, newSignalType.value);
    if (!created) {
        toast.warn(`A signal named '${newSignalName.value.trim()}' already exists.`);
        return;
    }
    newSignalName.value = "";
    newSignalType.value = "";
}

// --- presentation helpers ------------------------------------------------ //

const TYPE_BADGES: Record<string, string> = {
    bit: "bg-green-900/60 text-green-300 border border-green-700",
    float: "bg-blue-900/60 text-blue-300 border border-blue-700",
    s32: "bg-amber-900/60 text-amber-300 border border-amber-700",
    u32: "bg-purple-900/60 text-purple-300 border border-purple-700",
};

function typeBadgeClass(type: string): string {
    if (!type) return "bg-gray-700 text-gray-400 border border-gray-600";
    return TYPE_BADGES[type] ?? TYPE_BADGES.float;
}

// The BaseCard root owns its own border palette, so the drop
// affordance (ring) and the rejection feedback (red + shake) live on
// an inner wrapper inside the card body.
function signalDropZoneClass(signal: VisualSignal): string {
    if (rejectedSignalId.value === signal.id) {
        return "border-red-500 ring-2 ring-red-500 hal-card-reject";
    }
    if (dragOverSignalId.value === signal.id) {
        return "border-blue-400 ring-2 ring-blue-400";
    }
    return "border-gray-700";
}

// --- boot ----------------------------------------------------------------- //

const ready = computed(() => !store.loading && store.error === "");

onMounted(() => {
    void store.fetchLayout().then((ok) => {
        if (!ok) {
            toast.error(store.error || "Failed to load HAL layout.");
        }
    });
});
</script>

<template>
  <div class="flex flex-col gap-4 h-full" data-test="visual-hal-editor">
    <header class="flex flex-wrap items-baseline justify-between gap-3">
      <div>
        <h1 class="text-2xl font-bold">Visual HAL Editor</h1>
        <p class="text-sm text-gray-400">
          Drag an OUT pin onto a signal as its source, then drop IN pins as targets.
          Types must match; one source per signal.
        </p>
      </div>

      <div class="flex items-center gap-2">
        <BaseInput
          v-model="newSignalName"
          placeholder="signal-name"
          class="w-44"
          @keydown.enter.prevent="addSignal"
        />
        <BaseSelect v-model="newSignalType" title="Pre-set the signal type (auto adopts the first pin's type)">
          <option value="">auto</option>
          <option value="bit">bit</option>
          <option value="float">float</option>
          <option value="s32">s32</option>
          <option value="u32">u32</option>
        </BaseSelect>
        <BaseButton variant="primary" data-test="hal-new-signal" @click="addSignal">
          <template #icon><Icon name="plus" class="h-4 w-4" /></template>
          New Signal
        </BaseButton>
      </div>
    </header>

    <!-- Error / loading banners -->
    <div
      v-if="store.error"
      class="rounded-md border border-red-700 bg-red-900/40 text-red-300 px-4 py-3 text-sm"
      data-test="hal-error"
    >
      {{ store.error }}
    </div>
    <div v-else-if="store.loading" class="text-sm text-gray-400">Loading HAL layout…</div>

    <!-- Three-column board -->
    <div v-if="ready" class="grid grid-cols-1 lg:grid-cols-12 gap-4 flex-1 min-h-0">

      <!-- LEFT: IN pins (readers) -->
      <BaseCard title="IN pins (readers)" class="lg:col-span-3 flex flex-col min-h-0">
        <div class="max-h-[65vh] overflow-y-auto space-y-2" data-test="hal-in-pins">
          <div
            v-for="pin in store.inPins"
            :key="pin.id"
            draggable="true"
            class="rounded-md bg-gray-900 border border-gray-700 px-3 py-2 cursor-grab active:cursor-grabbing select-none hover:border-gray-500 transition-colors"
            :class="{ 'opacity-50': draggingPinId === pin.id }"
            :title="pin.description"
            @dragstart="onPinDragStart($event, pin)"
            @dragend="onPinDragEnd"
          >
            <div class="flex items-center justify-between gap-2">
              <span class="text-sm font-mono truncate">{{ pin.full_name }}</span>
              <span class="shrink-0 rounded px-1.5 py-0.5 text-xs font-mono" :class="typeBadgeClass(pin.type)">{{ pin.type }}</span>
            </div>
          </div>
          <p v-if="store.inPins.length === 0" class="text-xs text-gray-500 px-1">No IN pins available.</p>
        </div>
      </BaseCard>

      <!-- MIDDLE: signals -->
      <BaseCard title="Signals (wires)" class="lg:col-span-6 flex flex-col min-h-0">
        <template #header-actions>
          <span class="rounded bg-gray-700 px-1.5 py-0.5 text-xs text-gray-400">{{ store.signals.length }}</span>
        </template>
        <div class="max-h-[65vh] overflow-y-auto space-y-3" data-test="hal-signals">
          <BaseCard
            v-for="signal in store.signals"
            :key="signal.id"
            :title="signal.name"
            class="hal-signal-card"
            :data-test-signal="signal.name"
            @dragover="onSignalDragOver($event, signal)"
            @dragleave="onSignalDragLeave(signal)"
            @drop="onSignalDrop($event, signal)"
          >
            <template #header-actions>
              <span class="rounded px-1.5 py-0.5 text-xs font-mono" :class="typeBadgeClass(signal.type)">
                {{ signal.type || "untyped" }}
              </span>
              <span
                v-if="signal.isDraft"
                class="rounded bg-yellow-900/60 border border-yellow-700 text-yellow-300 px-1.5 py-0.5 text-xs"
              >draft</span>
              <BaseButton
                variant="ghost"
                size="sm"
                title="Delete signal"
                @click="store.removeSignal(signal.id)"
              >
                <template #icon><Icon name="close" class="h-4 w-4" /></template>
              </BaseButton>
            </template>

            <!-- Drop target: rings blue while a valid drag hovers, shakes red on rejection. -->
            <div class="rounded-md border-2 border-dashed p-3 transition-colors" :class="signalDropZoneClass(signal)">
              <!-- Source slot (exactly one OUT pin) -->
              <div class="mb-3">
                <p class="text-xs uppercase tracking-wide text-gray-500 mb-1">Source (OUT)</p>
                <div v-if="signal.source" class="flex items-center justify-between gap-2 rounded-md bg-green-950/50 border border-green-800 px-3 py-1.5">
                  <span class="text-sm font-mono truncate">{{ signal.source.full_name }}</span>
                  <BaseButton
                    variant="ghost"
                    size="sm"
                    title="Disconnect source"
                    @click="store.removeSource(signal.id)"
                  >
                    <template #icon><Icon name="close" class="h-3.5 w-3.5" /></template>
                  </BaseButton>
                </div>
                <p v-else class="text-xs text-gray-500 border border-gray-700 border-dashed rounded-md px-3 py-1.5">
                  Drop an OUT pin here…
                </p>
              </div>

              <!-- Targets list (N IN pins) -->
              <div>
                <p class="text-xs uppercase tracking-wide text-gray-500 mb-1">Targets (IN)</p>
                <div class="space-y-1.5">
                  <div
                    v-for="target in signal.targets"
                    :key="target.id"
                    class="flex items-center justify-between gap-2 rounded-md bg-gray-800 border border-gray-700 px-3 py-1.5"
                  >
                    <span class="text-sm font-mono truncate">{{ target.full_name }}</span>
                    <BaseButton
                      variant="ghost"
                      size="sm"
                      title="Disconnect target"
                      @click="store.removeTarget(signal.id, target.id)"
                    >
                      <template #icon><Icon name="close" class="h-3.5 w-3.5" /></template>
                    </BaseButton>
                  </div>
                  <p class="text-xs text-gray-500 border border-gray-700 border-dashed rounded-md px-3 py-1.5">
                    Drop IN pins here… (multiple allowed)
                  </p>
                </div>
              </div>
            </div>
          </BaseCard>

          <p v-if="store.signals.length === 0" class="text-xs text-gray-500 px-1 py-6 text-center">
            No signals yet — create one with “New Signal”.
          </p>
        </div>
      </BaseCard>

      <!-- RIGHT: OUT pins (writers) -->
      <BaseCard title="OUT pins (writers)" class="lg:col-span-3 flex flex-col min-h-0">
        <div class="max-h-[65vh] overflow-y-auto space-y-2" data-test="hal-out-pins">
          <div
            v-for="pin in store.outPins"
            :key="pin.id"
            draggable="true"
            class="rounded-md bg-gray-900 border border-gray-700 px-3 py-2 cursor-grab active:cursor-grabbing select-none hover:border-gray-500 transition-colors"
            :class="{ 'opacity-50': draggingPinId === pin.id }"
            :title="pin.description"
            @dragstart="onPinDragStart($event, pin)"
            @dragend="onPinDragEnd"
          >
            <div class="flex items-center justify-between gap-2">
              <span class="text-sm font-mono truncate">{{ pin.full_name }}</span>
              <span class="shrink-0 rounded px-1.5 py-0.5 text-xs font-mono" :class="typeBadgeClass(pin.type)">{{ pin.type }}</span>
            </div>
          </div>
          <p v-if="store.outPins.length === 0" class="text-xs text-gray-500 px-1">No OUT pins available.</p>
        </div>
      </BaseCard>
    </div>
  </div>
</template>

<style scoped>
/* Rejected-drop feedback: short horizontal shake. */
@keyframes hal-shake {
    0%, 100% { transform: translateX(0); }
    20% { transform: translateX(-6px); }
    40% { transform: translateX(6px); }
    60% { transform: translateX(-4px); }
    80% { transform: translateX(4px); }
}

.hal-card-reject {
    animation: hal-shake 0.4s ease-in-out;
}
</style>
