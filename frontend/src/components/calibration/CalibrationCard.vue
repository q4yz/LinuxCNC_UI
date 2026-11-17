<script setup lang="ts">
// One calibration on the Calibration tab: last tested, result, reminder
// (once), benefit, instructions, its parameters and Start. Bed mesh opens
// its details in a pop-up; Probe Z offset shows the paper-test buttons
// while its session runs.
import { computed, ref, watch } from "vue";
import type { CalibrationItem } from "../../facades/calibrationFacade";
import { CALIBRATIONS, REMINDER_PRESETS, addDays, relativeDate } from "../../config/calibrations";
import { BaseButton, Icon } from "../../ui";
import BaseCard from "../../ui/BaseCard.vue";

const props = defineProps<{ item: CalibrationItem; busy?: boolean }>();
const emit = defineEmits<{
  start: [params: Record<string, number>];
  reminder: [date: string | null];
  clear: [];
  details: [];
  command: [line: string];
}>();

const text = computed(() => CALIBRATIONS[props.item.kind] ?? {
  title: props.item.id, benefit: "", steps: [], saves: "",
});
const title = computed(() => (props.item.label ? `${text.value.title}: ${props.item.label}` : text.value.title));
const showSteps = ref(false);
const editingReminder = ref(false);
const reminderDate = ref(props.item.remind_at ?? "");
watch(() => props.item.remind_at, (v) => (reminderDate.value = v ?? ""));

const params = ref<Record<string, number>>({});
watch(
  () => props.item.params,
  (list) => {
    for (const p of list ?? []) if (params.value[p.name] === undefined) params.value[p.name] = p.default;
  },
  { immediate: true },
);

const session = computed(() => props.item.kind === "probe_z_offset" && !!props.item.values?.session);
const clearable = computed(() => ["probe_z_offset", "pid", "input_shaper"].includes(props.item.kind));
const status = computed(() => {
  if (!props.item.available) return { text: "not on this machine", cls: "bg-gray-700 text-gray-400" };
  if (props.item.running || session.value) return { text: "running", cls: "bg-blue-700/60 text-blue-100" };
  if (props.item.due) return { text: "due", cls: "bg-amber-600/70 text-amber-50" };
  return null;
});

const inUse = computed(() => {
  const v = props.item.values ?? {};
  const fmt = (x: unknown, d = 3) => (typeof x === "number" ? x.toFixed(d) : "—");
  switch (props.item.kind) {
    case "pid":
      return `Kp ${fmt(v.kp)}  Ki ${fmt(v.ki)}  Kd ${fmt(v.kd)}${v.calibrated ? " (calibrated)" : " (profile)"}`;
    case "probe_z_offset":
      return `z_offset ${fmt(v.z_offset)} mm`;
    case "input_shaper":
      return `X ${v.type_x ?? "—"} ${fmt(v.freq_x, 1)} Hz, Y ${v.type_y ?? "—"} ${fmt(v.freq_y, 1)} Hz`;
    default:
      return "";
  }
});

function setPreset(days: number) {
  emit("reminder", addDays(days));
  editingReminder.value = false;
}
function saveReminder() {
  emit("reminder", reminderDate.value || null);
  editingReminder.value = false;
}
</script>

<template>
  <!-- BaseCard: its header moves its right side clear of the STOP box -->
  <BaseCard
    :title="title"
    :stagger="false"
    class="flex w-80 max-w-[calc(100vw-6rem)] shrink-0 snap-start flex-col"
    :class="item.due && item.available ? 'ring-1 ring-amber-500/70' : ''"
    :data-testid="`calibration-card-${item.id}`"
  >
    <template #header-actions>
      <span v-if="status" class="shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase" :class="status.cls">
        {{ status.text }}
      </span>
    </template>

    <div class="flex h-full flex-col gap-3 p-4 text-sm">
      <dl class="grid grid-cols-[6.5rem_1fr] gap-x-2 gap-y-1">
        <dt class="text-gray-500">Last tested</dt>
        <dd class="text-gray-200" :title="item.last_tested ?? ''" data-testid="calibration-last">
          {{ relativeDate(item.last_tested) }}
        </dd>
        <dt class="text-gray-500">Result</dt>
        <dd class="break-words font-mono text-xs text-gray-200" data-testid="calibration-result">
          {{ item.result || "—" }}
        </dd>
        <template v-if="inUse">
          <dt class="text-gray-500">In use</dt>
          <dd class="font-mono text-xs text-gray-300">{{ inUse }}</dd>
        </template>
        <dt class="text-gray-500">Reminder</dt>
        <dd class="text-gray-200">
          <button
            v-if="!editingReminder"
            type="button"
            class="text-left underline decoration-dotted underline-offset-2 hover:text-white"
            :class="item.due ? 'text-amber-300' : ''"
            data-testid="calibration-reminder"
            @click="editingReminder = true"
          >{{ item.remind_at ? `${item.remind_at}${item.due ? " (due)" : ""}` : "none — set" }}</button>
          <div v-else class="space-y-1">
            <input
              v-model="reminderDate"
              type="date"
              class="w-full rounded border border-gray-600 bg-gray-900 px-2 py-1 text-xs text-gray-200"
              data-testid="calibration-reminder-date"
            />
            <div class="flex flex-wrap gap-1">
              <button
                v-for="preset in REMINDER_PRESETS"
                :key="preset.days"
                type="button"
                class="rounded bg-gray-700 px-1.5 py-0.5 text-[11px] text-gray-200 hover:bg-gray-600"
                @click="setPreset(preset.days)"
              >{{ preset.label }}</button>
            </div>
            <div class="flex gap-1">
              <BaseButton size="sm" variant="primary" @click="saveReminder">Save</BaseButton>
              <BaseButton v-if="item.remind_at" size="sm" variant="ghost" @click="emit('reminder', null); editingReminder = false">Remove</BaseButton>
              <BaseButton size="sm" variant="ghost" @click="editingReminder = false">Cancel</BaseButton>
            </div>
          </div>
        </dd>
      </dl>

      <p class="text-gray-400">{{ text.benefit }}</p>

      <div>
        <button
          type="button"
          class="flex items-center gap-1 text-xs font-semibold uppercase tracking-wider text-gray-400 hover:text-gray-200"
          @click="showSteps = !showSteps"
        >
          <Icon name="chevronDown" class="h-3 w-3 transition-transform" :class="showSteps ? '' : '-rotate-90'" />
          Instructions
        </button>
        <ol v-if="showSteps" class="mt-2 list-decimal space-y-1 pl-5 text-xs text-gray-300" data-testid="calibration-steps">
          <li v-for="(step, k) in text.steps" :key="k">{{ step }}</li>
        </ol>
        <p v-if="showSteps && text.saves" class="mt-2 text-xs text-gray-500">Saved: {{ text.saves }}</p>
      </div>

      <p v-if="!item.available" class="rounded bg-gray-900/60 p-2 text-xs text-gray-400">{{ item.reason }}</p>

      <div v-if="session" class="space-y-2 rounded border border-blue-700/60 bg-blue-900/20 p-2" data-testid="calibration-paper-test">
        <p class="text-xs text-blue-100">Lower the nozzle until the paper just drags:</p>
        <div class="grid grid-cols-4 gap-1">
          <BaseButton v-for="dz in [-0.1, -0.01, 0.01, 0.1]" :key="dz" size="sm" variant="secondary" :disabled="busy || item.running"
                      @click="emit('command', `TESTZ Z=${dz}`)">{{ dz > 0 ? "+" : "" }}{{ dz }}</BaseButton>
        </div>
        <div class="flex gap-2">
          <BaseButton size="sm" variant="success" :disabled="busy || item.running" @click="emit('command', 'ACCEPT')">Accept</BaseButton>
          <BaseButton size="sm" variant="danger" :disabled="busy" @click="emit('command', 'ABORT')">Abort</BaseButton>
        </div>
      </div>

      <div class="mt-auto space-y-2">
        <label v-for="p in item.params" :key="p.name" class="flex items-center justify-between gap-2 text-xs text-gray-400">
          <span class="capitalize">{{ p.name }}</span>
          <span class="flex items-center gap-1">
            <input
              v-model.number="params[p.name]"
              type="number"
              step="any"
              :min="p.minimum ?? undefined"
              :max="p.maximum ?? undefined"
              class="w-20 rounded border border-gray-600 bg-gray-900 px-2 py-1 text-right font-mono text-gray-200"
              :data-testid="`calibration-param-${item.id}-${p.name}`"
            />
            <span class="w-6">{{ p.unit }}</span>
          </span>
        </label>
        <div class="flex flex-wrap gap-2">
          <BaseButton
            variant="primary"
            size="sm"
            :disabled="busy || !item.available || item.running || session"
            :data-testid="`calibration-start-${item.id}`"
            @click="emit('start', { ...params })"
          >{{ item.running || session ? "Running…" : "Start" }}</BaseButton>
          <BaseButton
            v-if="item.kind === 'bed_mesh'"
            variant="secondary"
            size="sm"
            data-testid="calibration-details-bed_mesh"
            @click="emit('details')"
          ><Icon name="mesh" class="mr-1" /> Details</BaseButton>
          <BaseButton
            v-if="clearable && item.available"
            variant="ghost"
            size="sm"
            :disabled="busy || item.running"
            title="Remove the saved values: back to the profile's"
            @click="emit('clear')"
          >Clear</BaseButton>
        </div>
      </div>
    </div>
  </BaseCard>
</template>
