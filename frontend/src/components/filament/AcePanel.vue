<script setup lang="ts">
// The ACE Pro card ([ace]): the four slots (RFID colour, material, loaded /
// empty), loading one (M640 through MDI: park, cut, change, purge),
// unloading, the change's progress and errors, the filament sensors, the
// dryer, and a manual feed / wind back for setting up. Hidden on machines
// without an [ace].
import { computed, ref } from "vue";
import { storeToRefs } from "pinia";

import BaseButton from "../../ui/BaseButton.vue";
import BaseCard from "../../ui/BaseCard.vue";
import { useAce } from "../../composables/useAce";
import { useAuthStore } from "../../stores/authStore";
import { SystemState, useMachineStore } from "../../stores/stateFacade";

const ace = useAce();
const { state, busy } = ace;
const auth = useAuthStore();
const { systemState } = storeToRefs(useMachineStore());

const SLOT_COUNT = 4;
const NO_SLOT = -1;
const UNKNOWN_SLOT = -2;

const configured = computed(() => state.value?.configured === true);
const connected = computed(() => state.value?.connected === true);
const changing = computed(() => state.value?.changing === true);
const current = computed(() => state.value?.current_slot ?? NO_SLOT);

/** The four slots, also before the ACE answered (placeholders). */
const slots = computed(() =>
  Array.from({ length: SLOT_COUNT }, (_, index) => {
    const slot = state.value?.slots?.find((s) => s.index === index);
    return {
      index,
      ready: slot?.status === "ready",
      status: slot?.status || "—",
      // the material first (PLA, PETG): a narrow tile cuts the rest
      material: slot?.type || (slot?.status === "ready" ? "filament" : ""),
      brand: slot?.brand || "",
      color: slot?.status === "ready" && slot.color && slot.color.length >= 3
        ? `rgb(${slot.color[0]}, ${slot.color[1]}, ${slot.color[2]})` : null,
    };
  }),
);

// A change moves the machine through MDI: only while it stands still.
const machineIdle = computed(() => ([SystemState.IDLE, SystemState.LOADED] as string[]).includes(systemState.value));
const canChange = computed(() =>
  connected.value && !changing.value && !busy.value && machineIdle.value && auth.can("machine.motion"));
const canUnit = computed(() => connected.value && !changing.value && !busy.value && auth.can("heaters.control"));
const changeHint = computed(() => {
  if (!connected.value) return "The ACE is not connected";
  if (changing.value) return "A tool change is running";
  if (!machineIdle.value) return "Only while the machine is on and idle (a print changes by itself)";
  if (!auth.can("machine.motion")) return "Log in to change filament";
  return "";
});

const currentText = computed(() => {
  if (current.value === NO_SLOT) return "none";
  if (current.value === UNKNOWN_SLOT) return "unknown";
  return `T${current.value}`;
});

function sensorClass(value: boolean | null | undefined): string {
  if (value === null || value === undefined) return "bg-gray-700 text-gray-400";
  return value ? "bg-green-700 text-green-100" : "bg-gray-700 text-gray-300";
}

function sensorText(value: boolean | null | undefined): string {
  if (value === null || value === undefined) return "?";
  return value ? "filament" : "empty";
}

// -- correcting the loaded slot after handling filament by hand -- //
const correction = ref<number>(NO_SLOT);
async function applyCorrection() {
  await ace.setCurrent(correction.value);
}

// -- dryer -- //
const dryTemp = ref(45);
const dryMinutes = ref(240);
const drying = computed(() => state.value?.dryer?.drying === true);

// -- manual feed / wind back (setup) -- //
const manualOpen = ref(false);
const manualSlot = ref(0);
const manualLength = ref(50);
const manualSpeed = ref(20);
</script>

<template>
  <BaseCard v-if="configured" title="ACE Pro" data-testid="ace-panel">
    <template #header-actions>
      <span
        class="rounded px-2 py-0.5 text-xs"
        :class="connected ? 'bg-green-800 text-green-100' : 'bg-red-900 text-red-100'"
        :title="connected ? `${state?.model} ${state?.firmware}` : 'Not connected'"
        data-testid="ace-link"
      >
        {{ connected ? (state?.status === "busy" ? state?.action || "busy" : "ready") : "offline" }}
      </span>
    </template>

    <div class="space-y-4 p-4 text-sm">
      <!-- the change in progress / the last error -->
      <div v-if="changing" class="rounded border border-blue-700 bg-blue-950/60 px-3 py-2 text-blue-100" data-testid="ace-changing">
        Tool change: {{ state?.step || "working" }} …
      </div>
      <div v-else-if="state?.last_error" class="space-y-2 rounded border border-red-700 bg-red-950/50 px-3 py-2 text-red-100"
           role="alert" data-testid="ace-error">
        <p>{{ state.last_error }}</p>
        <div class="flex flex-wrap items-center gap-2 text-xs text-red-200">
          <span>Filament handled by hand? Loaded now:</span>
          <select v-model.number="correction" class="rounded border border-red-700 bg-gray-900 px-2 py-1"
                  data-testid="ace-correction">
            <option :value="-1">none</option>
            <option v-for="n in SLOT_COUNT" :key="n" :value="n - 1">T{{ n - 1 }}</option>
          </select>
          <BaseButton size="sm" variant="secondary" :disabled="busy || !auth.can('machine.tune')" @click="applyCorrection">
            Set
          </BaseButton>
        </div>
      </div>

      <!-- slots -->
      <div class="grid grid-cols-2 gap-2 sm:grid-cols-4" data-testid="ace-slots">
        <div
          v-for="slot in slots"
          :key="slot.index"
          class="flex flex-col gap-2 rounded border p-2"
          :class="current === slot.index ? 'border-blue-500 bg-blue-950/40' : 'border-gray-700 bg-gray-900/50'"
          :data-testid="`ace-slot-${slot.index}`"
        >
          <div class="flex items-center gap-2">
            <span
              class="h-6 w-6 shrink-0 rounded-full border border-gray-500"
              :style="slot.color ? { background: slot.color } : {}"
              :class="slot.color ? '' : 'bg-gray-800'"
            />
            <div class="min-w-0">
              <div class="font-medium text-gray-100">T{{ slot.index }}</div>
              <div class="truncate text-xs text-gray-400" :title="slot.brand">{{ slot.ready ? slot.material : slot.status }}</div>
            </div>
          </div>
          <span v-if="current === slot.index" class="text-xs font-semibold text-blue-300">loaded</span>
          <BaseButton
            v-else
            size="sm"
            variant="primary"
            :disabled="!canChange || !slot.ready"
            :title="changeHint || (slot.ready ? `Load T${slot.index}` : 'No filament in this slot')"
            :data-testid="`ace-load-${slot.index}`"
            @click="ace.load(slot.index)"
          >
            Load
          </BaseButton>
        </div>
      </div>

      <!-- loaded slot, sensors, unload -->
      <div class="flex flex-wrap items-center gap-2 text-xs text-gray-300">
        <span>Loaded: <b class="text-gray-100" data-testid="ace-current">{{ currentText }}</b></span>
        <span class="rounded px-2 py-0.5" :class="sensorClass(state?.toolhead_sensor)" data-testid="ace-toolhead-sensor">
          toolhead: {{ sensorText(state?.toolhead_sensor) }}
        </span>
        <span v-if="state?.hub_sensor !== null && state?.hub_sensor !== undefined"
              class="rounded px-2 py-0.5" :class="sensorClass(state?.hub_sensor)">
          hub: {{ sensorText(state?.hub_sensor) }}
        </span>
        <span class="flex-1" />
        <BaseButton
          size="sm"
          variant="secondary"
          :disabled="!canChange || current === NO_SLOT"
          :title="changeHint || 'Cut and wind the loaded filament back'"
          data-testid="ace-unload"
          @click="ace.unload()"
        >
          Unload
        </BaseButton>
      </div>

      <!-- dryer -->
      <div class="flex flex-wrap items-center gap-2 border-t border-gray-700 pt-3 text-xs text-gray-300" data-testid="ace-dryer">
        <span class="font-medium text-gray-200">Dryer</span>
        <template v-if="drying">
          <span>{{ state?.dryer?.target_temp ?? "?" }} °C, {{ state?.dryer?.remain_min ?? "?" }} min left
            (inside {{ state?.temp ?? "?" }} °C)</span>
          <span class="flex-1" />
          <BaseButton size="sm" variant="secondary" :disabled="!canUnit" @click="ace.stopDrying()">Stop</BaseButton>
        </template>
        <template v-else>
          <input v-model.number="dryTemp" type="number" min="35" max="55"
                 class="w-16 rounded border border-gray-600 bg-gray-900 px-2 py-1" aria-label="Drying temperature" />
          <span>°C</span>
          <input v-model.number="dryMinutes" type="number" min="1" max="240"
                 class="w-16 rounded border border-gray-600 bg-gray-900 px-2 py-1" aria-label="Drying time" />
          <span>min</span>
          <span class="flex-1" />
          <BaseButton size="sm" variant="secondary" :disabled="!canUnit" data-testid="ace-dry"
                      @click="ace.startDrying(dryTemp, dryMinutes)">
            Start
          </BaseButton>
        </template>
      </div>

      <!-- manual feed / wind back -->
      <div class="border-t border-gray-700 pt-3 text-xs text-gray-300">
        <button type="button" class="text-gray-400 hover:text-gray-200" @click="manualOpen = !manualOpen">
          {{ manualOpen ? "▾" : "▸" }} Manual feed (setup)
        </button>
        <div v-if="manualOpen" class="mt-2 flex flex-wrap items-center gap-2" data-testid="ace-manual">
          <select v-model.number="manualSlot" class="rounded border border-gray-600 bg-gray-900 px-2 py-1" aria-label="Slot">
            <option v-for="n in SLOT_COUNT" :key="n" :value="n - 1">T{{ n - 1 }}</option>
          </select>
          <input v-model.number="manualLength" type="number" min="1" max="2000"
                 class="w-20 rounded border border-gray-600 bg-gray-900 px-2 py-1" aria-label="Length (mm)" />
          <span>mm at</span>
          <input v-model.number="manualSpeed" type="number" min="1" max="80"
                 class="w-16 rounded border border-gray-600 bg-gray-900 px-2 py-1" aria-label="Speed (mm/s)" />
          <span>mm/s</span>
          <BaseButton size="sm" variant="secondary" :disabled="!canUnit"
                      @click="ace.feed(manualSlot, manualLength, manualSpeed)">Feed</BaseButton>
          <BaseButton size="sm" variant="secondary" :disabled="!canUnit"
                      @click="ace.unwind(manualSlot, manualLength, manualSpeed)">Wind back</BaseButton>
        </div>
      </div>
    </div>
  </BaseCard>
</template>
