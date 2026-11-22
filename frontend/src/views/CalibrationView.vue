<script setup lang="ts">
// Calibration tab: one card per calibration of the machine, side by side
// (scroll sideways). Results and reminders live in the machine's
// calibration.ini (backend CalibrationService). The bed mesh's details —
// the mesh list, heatmap, editing — open in a pop-up.
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { calibrationFacade, type CalibrationItem } from "../facades/calibrationFacade";
import { printTuningFacade } from "../facades/printTuningFacade";
import { machineLifecycleFacade } from "../facades/machineLifecycleFacade";
import CalibrationCard from "../components/calibration/CalibrationCard.vue";
import BedMeshView from "./BedMeshView.vue";
import { BaseButton, Icon } from "../ui";
import { describeError } from "../core/error-format";
import { useConsoleStore } from "../stores/console";
import { useCalibrationDue } from "../composables/useCalibrationDue";
import { scheduleEstopCheck } from "../ui/estopClearance";
import { ModalButtonStyle, useConfirm } from "../core/confirm";

const consoleStore = useConsoleStore();
const { setDue } = useCalibrationDue();

const items = ref<CalibrationItem[]>([]);
const loaded = ref(false);
const unavailable = ref(false);
const busy = ref(false);
const meshOpen = ref(false);
const scroller = ref<HTMLElement | null>(null);
let timer: ReturnType<typeof setTimeout> | null = null;

const anyRunning = computed(() => items.value.some((i) => i.running || (i.kind === "probe_z_offset" && i.values?.session)));
const due = computed(() => items.value.filter((i) => i.due && i.available).length);

function apply(list: { items: CalibrationItem[]; due?: number }) {
  items.value = list.items;
  setDue(list.due ?? 0);
}

async function refresh() {
  try {
    apply(await calibrationFacade.list());
    unavailable.value = false;
  } catch {
    unavailable.value = true;
  } finally {
    loaded.value = true;
  }
  if (timer) clearTimeout(timer);
  // fast while a calibration runs, slow otherwise
  timer = setTimeout(refresh, anyRunning.value ? 2000 : 10000);
}

async function act<T>(what: string, call: () => Promise<T>): Promise<T | undefined> {
  busy.value = true;
  try {
    return await call();
  } catch (err) {
    consoleStore.error(`Calibration: ${what} failed: ${describeError(err)}`);
    return undefined;
  } finally {
    busy.value = false;
  }
}

async function start(item: CalibrationItem, params: Record<string, number>) {
  if (item.guided) {
    const ok = await useConfirm({
      title: "Print a test object",
      question: `Heats to ${params.hotend ?? "?"} °C / ${params.bed ?? "?"} °C, homes and prints the test object. Is the bed clear and filament loaded?`,
      confirmButtonText: "Print",
      confirmButtonStyle: ModalButtonStyle.PRIMARY,
      rejectButtonText: "Cancel",
    });
    if (!ok) return;
  }
  const command = await act(`starting ${item.id}`, () => calibrationFacade.start(item.id, params));
  if (command) consoleStore.info(`Calibration started: ${command}`);
  await refresh();
}

async function reminder(item: CalibrationItem, date: string | null) {
  const list = await act("saving the reminder", () => calibrationFacade.setReminder(item.id, date));
  if (list) apply(list);
}

async function clear(item: CalibrationItem) {
  const list = await act("clearing", () => calibrationFacade.clear(item.id));
  if (list) {
    apply(list);
    consoleStore.success("Calibration cleared: the profile's values from the next machine start.");
  }
}

async function submit(item: CalibrationItem, values: Record<string, number>) {
  const response = await act("saving the result", () => calibrationFacade.submit(item.id, values));
  if (!response) return;
  apply(response.calibrations);
  consoleStore.success(`Calibration: ${response.result}`);
}

// first layer: the live Z offset (print tuning), + = nozzle up; null = back to 0
async function liveZ(delta: number | null) {
  await act("changing the live Z offset", () =>
    delta === null ? printTuningFacade.setZ(0) : printTuningFacade.adjustZ(delta),
  );
  await refresh();
}

// sensorless homing: save the threshold, then restart LinuxCNC so the
// board config (synced at the start) carries it to the driver
async function threshold(item: CalibrationItem, value: number) {
  const ok = await useConfirm({
    title: `Sensorless homing ${item.label}`,
    question: `Save threshold ${value} and restart LinuxCNC now? The machine goes off; switch it on and home ${item.label} again.`,
    confirmButtonText: "Save & restart",
    confirmButtonStyle: ModalButtonStyle.PRIMARY,
    rejectButtonText: "Cancel",
  });
  if (!ok) return;
  const response = await act("saving the threshold", () => calibrationFacade.submit(item.id, { threshold: value }));
  if (!response) return;
  consoleStore.info(response.result);
  const restarted = await act("restarting LinuxCNC", async () => {
    await machineLifecycleFacade.stopMachine();
    return machineLifecycleFacade.startMachine();
  });
  if (restarted) consoleStore.success(`LinuxCNC restarted with threshold ${value} — switch on and home ${item.label}.`);
  await refresh();
}

async function command(line: string) {
  await act(line, () => calibrationFacade.command(line));
  await refresh();
}

function scrollBy(direction: number) {
  const el = scroller.value;
  const card = el?.firstElementChild as HTMLElement | null | undefined;
  // one card (and the gap) per click
  if (el) el.scrollBy({ left: direction * ((card?.offsetWidth ?? 320) + 16), behavior: "smooth" });
}

function onKey(event: KeyboardEvent) {
  if (event.key === "Escape") meshOpen.value = false;
}

onMounted(() => {
  refresh();
  window.addEventListener("keydown", onKey);
});
onBeforeUnmount(() => {
  if (timer) clearTimeout(timer);
  window.removeEventListener("keydown", onKey);
});
</script>

<template>
  <!-- everything on the left: the top right belongs to the STOP box -->
  <header class="flex flex-wrap items-center gap-3">
    <h1 class="flex items-center gap-3 text-2xl font-bold">
      Calibration
      <span v-if="due" class="rounded-full bg-amber-600 px-2 py-0.5 text-xs font-semibold text-white" data-testid="calibration-due">
        {{ due }} due
      </span>
    </h1>
    <!-- phones swipe; the arrows would sit under the STOP box there -->
    <div class="hidden gap-2 sm:flex">
      <BaseButton variant="secondary" size="sm" aria-label="Scroll left" @click="scrollBy(-1)">
        <template #icon><Icon name="chevronLeft" class="h-4 w-4" /></template>
      </BaseButton>
      <BaseButton variant="secondary" size="sm" aria-label="Scroll right" @click="scrollBy(1)">
        <template #icon><Icon name="chevronLeft" class="h-4 w-4 rotate-180" /></template>
      </BaseButton>
    </div>
  </header>

  <p v-if="unavailable" class="rounded border border-gray-700 bg-gray-800 p-4 text-sm text-gray-400">
    The machine backend does not answer — the calibrations show once it runs.
  </p>
  <p v-else-if="loaded && !items.length" class="text-sm text-gray-400">No calibrations for this machine.</p>

  <div
    ref="scroller"
    class="flex snap-x snap-mandatory items-stretch gap-4 overflow-x-auto pb-4"
    data-testid="calibration-scroller"
    @scroll.passive="scheduleEstopCheck"
  >
    <CalibrationCard
      v-for="item in items"
      :key="item.id"
      :item="item"
      :busy="busy"
      @start="(params) => start(item, params)"
      @reminder="(date) => reminder(item, date)"
      @clear="clear(item)"
      @details="meshOpen = true"
      @command="command"
      @submit="(values) => submit(item, values)"
      @live-z="liveZ"
      @threshold="(value) => threshold(item, value)"
    />
  </div>

  <div
    v-if="meshOpen"
    class="fixed inset-0 z-40 flex items-center justify-center bg-black/70 p-2 sm:p-6"
    data-testid="calibration-bed-mesh-dialog"
    @click.self="meshOpen = false"
  >
    <section class="flex max-h-full w-full max-w-6xl flex-col gap-4 overflow-y-auto rounded-lg border border-gray-600 bg-gray-900 p-4">
      <div class="flex justify-end">
        <BaseButton variant="secondary" size="sm" data-testid="calibration-bed-mesh-close" @click="meshOpen = false">
          <Icon name="close" class="mr-1 h-4 w-4" /> Close
        </BaseButton>
      </div>
      <BedMeshView />
    </section>
  </div>
</template>
