<script setup lang="ts">
// Bed mesh page: saved meshes (system service) as a list, the selected
// one as a heatmap you can edit, and the compensation switch (machine
// backend — only while a LinuxCNC session runs). See bedMeshFacade.
import { computed, onMounted, ref } from "vue";
import { bedMeshFacade, type BedMeshDefaults, type BedMeshGrid } from "../facades/bedMeshFacade";
import BedMeshHeatmap from "../components/bedmesh/BedMeshHeatmap.vue";
import { BaseButton, Icon } from "../ui";
import BaseCard from "../ui/BaseCard.vue";
import BaseInput from "../ui/BaseInput.vue";
import { ModalButtonStyle, useConfirm } from "../core/confirm";
import { describeError } from "../core/error-format";
import { useConsoleStore } from "../stores/console";

const consoleStore = useConsoleStore();

const names = ref<string[]>([]);
const active = ref<string | null>(null);
const selected = ref<BedMeshGrid | null>(null);
const draft = ref<BedMeshGrid | null>(null); // the edit copy while editing
const busy = ref(false);

// null: unknown (no LinuxCNC session / machine backend down)
const compensation = ref<boolean | null>(null);

const createOpen = ref(false);
const newName = ref("");
const newSpec = ref<BedMeshDefaults | null>(null);

const shown = computed(() => draft.value ?? selected.value);

async function run<T>(action: string, call: () => Promise<T>): Promise<T | undefined> {
  busy.value = true;
  try {
    return await call();
  } catch (err) {
    consoleStore.error(`Bed mesh: ${action} failed: ${describeError(err)}`);
    return undefined;
  } finally {
    busy.value = false;
  }
}

async function refresh() {
  const listing = await run("listing meshes", bedMeshFacade.list);
  if (!listing) return;
  names.value = listing.names ?? [];
  active.value = listing.active ?? null;
  if (selected.value && !names.value.includes(selected.value.name)) selected.value = null;
  if (!selected.value && names.value.length) await select(active.value ?? names.value[0]);
}

async function select(name: string) {
  draft.value = null;
  const grid = await run(`reading ${name}`, () => bedMeshFacade.read(name));
  if (grid) selected.value = grid;
}

async function activate(name: string) {
  const listing = await run(`activating ${name}`, () => bedMeshFacade.activate(name));
  if (!listing) return;
  active.value = listing.active ?? null;
  consoleStore.success(
    compensation.value
      ? `Bed mesh ${name} is active — switch compensation off and on to load it.`
      : `Bed mesh ${name} is active.`,
  );
}

async function remove(name: string) {
  const ok = await useConfirm({
    title: "Delete bed mesh",
    question: `Delete bed mesh "${name}"?`,
    confirmButtonText: "Delete",
    confirmButtonStyle: ModalButtonStyle.DANGER,
    rejectButtonText: "Cancel",
  });
  if (!ok) return;
  if (await run(`deleting ${name}`, () => bedMeshFacade.remove(name))) await refresh();
}

function startEdit() {
  if (selected.value) draft.value = JSON.parse(JSON.stringify(selected.value));
}

function setCell(row: number, col: number, value: number) {
  if (draft.value) draft.value.z[row][col] = value;
}

async function saveEdit() {
  if (!draft.value) return;
  const saved = await run(`saving ${draft.value.name}`, () => bedMeshFacade.save(draft.value!));
  if (!saved) return;
  selected.value = saved;
  draft.value = null;
  consoleStore.success(`Bed mesh ${saved.name} saved.`);
}

async function openCreate() {
  newName.value = "";
  newSpec.value = (await run("reading the grid defaults", bedMeshFacade.defaults)) ?? null;
  createOpen.value = newSpec.value !== null;
}

async function create() {
  if (!newSpec.value || !newName.value.trim()) return;
  const grid = await run("creating the mesh", () =>
    bedMeshFacade.create({ ...newSpec.value!, name: newName.value.trim() }),
  );
  if (!grid) return;
  createOpen.value = false;
  await refresh();
  await select(grid.name);
}

async function loadCompensation() {
  try {
    compensation.value = await bedMeshFacade.isEnabled();
  } catch {
    compensation.value = null;
  }
}

async function toggleCompensation() {
  if (compensation.value === null) return;
  const result = await run("switching compensation", () => bedMeshFacade.setEnabled(!compensation.value));
  if (result !== undefined) compensation.value = result;
}

onMounted(async () => {
  await Promise.all([refresh(), loadCompensation()]);
});
</script>

<template>
  <header class="flex flex-wrap items-baseline justify-between gap-3">
    <h1 class="text-2xl font-bold">Bed Mesh</h1>
    <div class="flex items-center gap-3 text-sm">
      <span class="text-gray-400">Compensation</span>
      <BaseButton
        :variant="compensation ? 'success' : 'secondary'"
        size="sm"
        :disabled="compensation === null || busy"
        :title="compensation === null ? 'Needs a running LinuxCNC session' : ''"
        data-testid="bed-mesh-compensation"
        @click="toggleCompensation"
      >{{ compensation === null ? "unavailable" : compensation ? "On" : "Off" }}</BaseButton>
    </div>
  </header>

  <div class="grid grid-cols-1 gap-6 pb-8 lg:grid-cols-[18rem_1fr]">
    <BaseCard class="flex flex-col">
      <div class="flex items-center justify-between border-b border-gray-600 bg-gray-700/50 px-4 py-3">
        <h2 class="text-sm font-semibold uppercase tracking-wider text-gray-300">Meshes</h2>
        <BaseButton variant="primary" size="sm" :disabled="busy" data-testid="bed-mesh-new" @click="openCreate">
          <Icon name="plus" class="mr-1" /> New
        </BaseButton>
      </div>
      <ul v-if="names.length" class="space-y-1 p-2" data-testid="bed-mesh-list">
        <li
          v-for="name in names"
          :key="name"
          class="flex cursor-pointer items-center gap-2 rounded border px-2 py-2"
          :class="selected?.name === name ? 'border-blue-500 bg-blue-600/30' : 'border-transparent hover:bg-gray-700/40'"
          @click="select(name)"
        >
          <Icon name="mesh" class="text-gray-400" />
          <span class="min-w-0 flex-1 truncate font-mono text-sm text-gray-200">{{ name }}</span>
          <span
            v-if="active === name"
            class="rounded bg-green-700/40 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-green-200"
          >active</span>
          <BaseButton
            v-else
            variant="ghost"
            size="sm"
            :disabled="busy"
            :data-testid="`bed-mesh-activate-${name}`"
            @click.stop="activate(name)"
          >Use</BaseButton>
          <BaseButton
            variant="ghost"
            size="sm"
            :disabled="busy || active === name"
            :title="active === name ? 'Activate another mesh first' : 'Delete'"
            :aria-label="`Delete ${name}`"
            @click.stop="remove(name)"
          >
            <template #icon><Icon name="trash" class="h-4 w-4" /></template>
          </BaseButton>
        </li>
      </ul>
      <p v-else class="p-6 text-center text-sm text-gray-500">No meshes yet — create one with New.</p>
    </BaseCard>

    <BaseCard class="flex flex-col">
      <div class="flex items-center justify-between border-b border-gray-600 bg-gray-700/50 px-4 py-3">
        <h2 class="font-mono text-sm font-semibold text-gray-300">{{ shown?.name ?? "No mesh selected" }}</h2>
        <div v-if="shown" class="flex gap-2">
          <template v-if="draft">
            <BaseButton variant="secondary" size="sm" :disabled="busy" @click="draft = null">Cancel</BaseButton>
            <BaseButton variant="success" size="sm" :disabled="busy" data-testid="bed-mesh-save" @click="saveEdit">
              <Icon name="save" class="mr-1" /> Save
            </BaseButton>
          </template>
          <BaseButton v-else variant="secondary" size="sm" :disabled="busy" data-testid="bed-mesh-edit" @click="startEdit">
            <Icon name="edit" class="mr-1" /> Edit
          </BaseButton>
        </div>
      </div>
      <div class="p-4">
        <BedMeshHeatmap v-if="shown" :grid="shown" :editable="!!draft" @update:cell="setCell" />
        <p v-else class="p-6 text-center text-sm text-gray-500">Select a mesh on the left.</p>
      </div>
    </BaseCard>
  </div>

  <div
    v-if="createOpen && newSpec"
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
    @click.self="createOpen = false"
  >
    <form class="w-full max-w-md space-y-4 rounded-lg border border-gray-600 bg-gray-800 p-4" @submit.prevent="create">
      <h3 class="font-semibold text-gray-100">New flat mesh</h3>
      <p class="text-xs text-gray-400">
        All Z offsets start at 0 — edit them, or overwrite the mesh with probe results later.
        The grid defaults to the machine's <code>probe_count</code> over its X / Y limits.
      </p>
      <BaseInput v-model="newName" autofocus type="text" placeholder="Name" class="w-full font-mono" data-testid="bed-mesh-new-name" />
      <div class="grid grid-cols-3 gap-2 text-xs text-gray-400">
        <span></span><span>min</span><span>max</span>
        <span class="self-center">X</span>
        <BaseInput v-model.number="newSpec.x_min" type="number" step="any" />
        <BaseInput v-model.number="newSpec.x_max" type="number" step="any" />
        <span class="self-center">Y</span>
        <BaseInput v-model.number="newSpec.y_min" type="number" step="any" />
        <BaseInput v-model.number="newSpec.y_max" type="number" step="any" />
        <span class="self-center">points X / Y</span>
        <BaseInput v-model.number="newSpec.x_count" type="number" min="2" />
        <BaseInput v-model.number="newSpec.y_count" type="number" min="2" />
      </div>
      <div class="flex justify-end gap-2">
        <BaseButton variant="secondary" @click="createOpen = false">Cancel</BaseButton>
        <BaseButton variant="primary" type="submit" :disabled="busy || !newName.trim()">Create</BaseButton>
      </div>
    </form>
  </div>
</template>
