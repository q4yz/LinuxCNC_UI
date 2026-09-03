<script setup lang="ts">
// Settings-pane editor for the per-module "custom macro buttons"
// config.
//
// Renders one row per ``slot`` declared by the host (e.g. DRO X /
// Y / Z, Camera viewer button). Each row exposes:
//
//   * an enable toggle,
//   * a name input (the button's label),
//   * a free-text icon input — the host renderer (``MacroButton``)
//     treats a known ``<Icon>`` name as an SVG glyph and any other
//     string (emoji, plain text) as a literal,
//   * a kind picker (``macro`` / ``ngc``; ``mcode`` is excluded —
//     see the comment in ``MacroButton.vue``),
//   * a macro dropdown sourced from the OpenAPI-generated client
//     ``ModulesMacrosService.listMacros`` (one fetch per kind on
//     mount). The editor does NOT go through the macros Pinia
//     store — that coupling used to leave the dropdown empty when
//     the editor mounted in a settings tab before the macros
//     store had been touched.
//
// The editor uses ``v-model`` against a ``MacroButtonDescriptor[]``.
// Persistence is the host's job (the host's ``@update:model-value``
// handler calls ``useMacroButtonConfig.persist``). The editor
// keeps a local draft and emits on input ``change`` events (not
// per keystroke) so a settings tab with five slots does not fire
// five writes per field edit.
//
// Slots the host declares but the operator has not configured yet
// are still rendered as rows — an empty row is the discoverable
// affordance. The editor keeps the row even when ``enabled`` is
// false so the operator can revisit a configuration without
// re-typing the slot id.

import { computed, onMounted, ref, watch } from "vue";
import type { PropType } from "vue";

import { ModulesMacrosService } from "../../generated/api";
import { useMacroButtonConfig } from "./useMacroButtonConfig";

// One editable row. Mirrors ``emptyDescriptor`` below; ``macroKind``
// is a closed union so the kind picker cannot produce junk state.
interface MacroButtonRow {
  slot: string;
  enabled: boolean;
  name: string;
  icon: string;
  macroKind: "macro" | "ngc";
  macroName: string;
}

// One host-declared button position (``id`` unique per host).
interface MacroButtonSlotDef {
  id: string;
  label?: string;
}

const props = defineProps({
  // Two-way bound list of descriptors. The host reads/writes this
  // through ``useMacroButtonConfig.persist``; the editor mutates a
  // working copy and emits on commit.
  modelValue: {
    type: Array as PropType<import("./useMacroButtonConfig").MacroButtonDescriptor[]>,
    required: true,
    default: () => [],
  },
  // Slot descriptors the host exposes. Each row in the editor
  // corresponds to one entry. ``id`` must be unique per host.
  slots: {
    type: Array as PropType<MacroButtonSlotDef[]>,
    required: true,
    default: () => [],
    validator: (v: unknown) =>
      Array.isArray(v) &&
      v.every(
        (s) =>
          s !== null &&
          typeof s === "object" &&
          typeof (s as MacroButtonSlotDef).id === "string",
      ),
  },
  // Owning module id — forwarded to ``useMacroButtonConfig`` for
  // the settings read/write path. The editor no longer depends on
  // the macros module being mounted (the dropdown is fetched via
  // the generated client), so the prop is informational here.
  moduleId: { type: String, required: true },
  // Helper-text shown above the table. Default keeps the
  // feature discoverable without forcing the host to write
  // marketing copy.
  description: {
    type: String,
    default:
      "Add a custom button to this surface. Leave the macro empty to hide the button.",
  },
});

const emit = defineEmits(["update:modelValue"]);

// Local working copy — the parent keeps the canonical
// ``modelValue``, this editor mutates a copy and emits on commit.
const draft = ref<MacroButtonRow[]>(normaliseDraft(props.modelValue, props.slots));

// Track which rows have unsaved local edits so we can suppress the
// v-model echo. Avoids the "type one character → persist → fetch
// back → re-mount input → focus loss" loop.
const dirty = ref(new Set<string>());

// Macro dropdown source — fetched directly from the backend via
// the generated ``ModulesMacrosService`` rather than going through
// the macros module's Pinia store. Bypassing the store keeps the
// editor decoupled from the macros module's lifecycle (the store
// is constructed lazily on first use of the macros store, so a  
// settings tab that mounts before any dashboard panel can mount
// before the store has been touched).
//
// ``mcode`` is intentionally excluded: an operator who needs an
// M-code call wraps it in a ``.macro`` file (see ``MacroButton.vue``).
const macroEntries = ref<string[]>([]);
const ngcEntries = ref<string[]>([]);
const macroLoadError = ref("");

async function loadMacroOptions() {
  macroLoadError.value = "";
  try {
    const [macroResp, ngcResp] = await Promise.all([
      ModulesMacrosService.listMacros("macro"),
      ModulesMacrosService.listMacros("ngc"),
    ]);
    // The generated ``MacroListResponse`` is
    // ``{ macros: MacroListItem[] }`` where each item is
    // ``{ name, kind, size_bytes }``. We only consume ``name``.
    macroEntries.value = Array.isArray(macroResp?.macros)
      ? macroResp.macros
          .map((row) => row?.name)
          .filter((n): n is string => Boolean(n))
      : [];
    ngcEntries.value = Array.isArray(ngcResp?.macros)
      ? ngcResp.macros
          .map((row) => row?.name)
          .filter((n): n is string => Boolean(n))
      : [];
  } catch (requestError) {
    macroEntries.value = [];
    ngcEntries.value = [];
    macroLoadError.value =
      requestError instanceof Error
        ? requestError.message
        : "Failed to load macro list";
  }
}

// One per kind, alphabetically sorted. The template picks the
// list matching the row's ``macroKind`` so a ``.macro`` row never
// accidentally shows ``.ngc`` files (and vice versa).
const macroOptionsByKind = computed(() => ({
  macro: [...macroEntries.value].sort((a, b) => a.localeCompare(b)),
  ngc: [...ngcEntries.value].sort((a, b) => a.localeCompare(b)),
}));

// When the parent replaces the array (e.g. another tab mutated
// the persisted payload), rebase the draft. We only overwrite rows
// that are not in the local dirty set so an in-flight edit is not
// stomped.
watch(
  () => props.modelValue,
  (next) => {
    for (const row of draft.value) {
      const incoming = Array.isArray(next)
        ? next.find((n) => n.slot === row.slot)
        : null;
      if (incoming && !dirty.value.has(row.slot)) {
        Object.assign(row, incoming);
      }
    }
    // Any slot the host newly declared should be appended.
    for (const slot of props.slots) {
      if (!draft.value.find((r) => r.slot === slot.id)) {
        draft.value.push(emptyDescriptor(slot.id));
      }
    }
  },
  { deep: true },
);

watch(
  () => props.slots,
  (next) => {
    for (const slot of next) {
      if (!draft.value.find((r) => r.slot === slot.id)) {
        draft.value.push(emptyDescriptor(slot.id));
      }
    }
  },
  { deep: true },
);

onMounted(() => {
  loadMacroOptions();
});

function emptyDescriptor(slot: string): MacroButtonRow {
  return {
    slot,
    enabled: false,
    name: "",
    icon: "",
    macroKind: "macro",
    macroName: "",
  };
}

/**
 * Seed the working draft from the parent payload, plus a fresh
 * empty row for any slot the host declared that the parent has
 * not yet configured.
 */
function normaliseDraft(
  payload: import("./useMacroButtonConfig").MacroButtonDescriptor[],
  slots: MacroButtonSlotDef[],
): MacroButtonRow[] {
  const rows: import("./useMacroButtonConfig").MacroButtonDescriptor[] =
    Array.isArray(payload) ? [...payload] : [];
  for (const slot of slots) {
    if (!rows.find((r) => r.slot === slot.id)) {
      rows.push(emptyDescriptor(slot.id));
    }
  }
  // Ensure every required field exists.
  return rows.map((r) => ({
    slot: r.slot,
    enabled: !!r.enabled,
    name: typeof r.name === "string" ? r.name : "",
    icon: typeof r.icon === "string" ? r.icon : "",
    macroKind: r.macroKind === "ngc" ? "ngc" : "macro",
    macroName: typeof r.macroName === "string" ? r.macroName : "",
  }));
}

function markDirty(slot: string) {
  dirty.value = new Set([...dirty.value, slot]);
}

function commitRow(row: MacroButtonRow) {
  dirty.value.delete(row.slot);
  emit("update:modelValue", draft.value.map((r) => ({ ...r })));
}

function onToggleEnabled(row: MacroButtonRow) {
  markDirty(row.slot);
  // Rows are normalised to the ``macro`` / ``ngc`` union, so the
  // legacy "coerce an invalid kind back to macro" branch cannot
  // fire any more.
  commitRow(row);
}

function onChangeName(row: MacroButtonRow) {
  markDirty(row.slot);
  commitRow(row);
}

function onChangeIcon(row: MacroButtonRow) {
  markDirty(row.slot);
  commitRow(row);
}

function onChangeKind(row: MacroButtonRow) {
  markDirty(row.slot);
  // Switching kind invalidates the macroName so the dropdown
  // does not silently keep a now-orphaned selection.
  row.macroName = "";
  commitRow(row);
}

function onChangeMacro(row: MacroButtonRow) {
  markDirty(row.slot);
  // ``<select>`` with a v-model emits per change; we treat
  // ``change`` here as the commit boundary.
  commitRow(row);
}

function descriptorFor(slot: MacroButtonSlotDef): MacroButtonRow | undefined {
  return draft.value.find((r) => r.slot === slot.id);
}

// Macro dropdown options scoped to the row's macroKind so a
// ``.macro`` row never silently lands a ``.ngc`` selection. The
// keep-the-label-prefix decision: the dropdown is short enough
// that an inline ``kind`` qualifier saves the operator a second
// read against the kind picker.
function optionsFor(row: MacroButtonRow | null | undefined): string[] {
  const kind = row?.macroKind === "ngc" ? "ngc" : "macro";
  return macroOptionsByKind.value[kind];
}
</script>

<template>
  <div class="space-y-3">
    <p class="text-xs text-gray-400">{{ description }}</p>

    <p
      v-if="macroLoadError"
      class="text-xs text-amber-300"
      role="alert"
    >
      {{ macroLoadError }} — the macro dropdown will be empty until the next refresh.
    </p>

    <div
      class="overflow-hidden rounded border border-gray-700 bg-gray-900/40"
      data-test="macro-button-editor"
    >
      <table class="min-w-full text-sm text-gray-200">
        <thead class="bg-gray-800/80 text-left text-xs uppercase tracking-wider text-gray-400">
          <tr>
            <th class="px-3 py-2">Slot</th>
            <th class="px-3 py-2">Enable</th>
            <th class="px-3 py-2">Name</th>
            <th class="px-3 py-2">Icon</th>
            <th class="px-3 py-2">Kind</th>
            <th class="px-3 py-2">Macro</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="slot in slots"
            :key="slot.id"
            class="border-t border-gray-800"
            :data-test="`macro-button-row-${slot.id}`"
          >
            <td class="px-3 py-2 align-top font-mono text-xs text-gray-400">
              {{ slot.label || slot.id }}
            </td>
            <td class="px-3 py-2 align-top">
              <input
                type="checkbox"
                class="h-5 w-5 rounded border-gray-600 bg-gray-900 text-blue-500 focus:ring-blue-500"
                :checked="descriptorFor(slot)?.enabled ?? false"
                :data-test="`macro-button-enable-${slot.id}`"
                @change="
                  (event) => {
                    const row = descriptorFor(slot);
                    if (!row) return;
                    row.enabled = (event.target as HTMLInputElement).checked;
                    onToggleEnabled(row);
                  }
                "
              />
            </td>
            <td class="px-3 py-2 align-top">
              <input
                type="text"
                :value="descriptorFor(slot)?.name ?? ''"
                placeholder="Button label"
                class="w-32 rounded border border-gray-600 bg-gray-900 px-2 py-1 text-xs text-gray-100 placeholder:text-gray-600 focus:border-blue-500 focus:outline-none"
                :data-test="`macro-button-name-${slot.id}`"
                @change="
                  (event) => {
                    const row = descriptorFor(slot);
                    if (!row) return;
                    row.name = (event.target as HTMLInputElement).value;
                    onChangeName(row);
                  }
                "
              />
            </td>
            <td class="px-3 py-2 align-top">
              <input
                type="text"
                :value="descriptorFor(slot)?.icon ?? ''"
                placeholder="💡 or icon name"
                class="w-28 rounded border border-gray-600 bg-gray-900 px-2 py-1 text-xs text-gray-100 placeholder:text-gray-600 focus:border-blue-500 focus:outline-none"
                :data-test="`macro-button-icon-${slot.id}`"
                @change="
                  (event) => {
                    const row = descriptorFor(slot);
                    if (!row) return;
                    row.icon = (event.target as HTMLInputElement).value;
                    onChangeIcon(row);
                  }
                "
              />
            </td>
            <td class="px-3 py-2 align-top">
              <select
                :value="descriptorFor(slot)?.macroKind ?? 'macro'"
                class="rounded border border-gray-600 bg-gray-900 px-2 py-1 text-xs text-gray-100 focus:border-blue-500 focus:outline-none"
                :data-test="`macro-button-kind-${slot.id}`"
                @change="
                  (event) => {
                    const row = descriptorFor(slot);
                    if (!row) return;
                    row.macroKind = (event.target as HTMLSelectElement).value === 'ngc' ? 'ngc' : 'macro';
                    onChangeKind(row);
                  }
                "
              >
                <option value="macro">macro</option>
                <option value="ngc">ngc</option>
              </select>
            </td>
            <td class="px-3 py-2 align-top">
              <select
                :value="descriptorFor(slot)?.macroName ?? ''"
                class="w-40 rounded border border-gray-600 bg-gray-900 px-2 py-1 text-xs text-gray-100 focus:border-blue-500 focus:outline-none"
                :data-test="`macro-button-macro-${slot.id}`"
                @change="
                  (event) => {
                    const row = descriptorFor(slot);
                    if (!row) return;
                    row.macroName = (event.target as HTMLSelectElement).value;
                    onChangeMacro(row);
                  }
                "
              >
                <option value="">— none —</option>
                <option
                  v-for="name in optionsFor(descriptorFor(slot))"
                  :key="name"
                  :value="name"
                >
                  {{ name }}
                </option>
              </select>
            </td>
          </tr>
          <tr v-if="slots.length === 0">
            <td
              colspan="6"
              class="px-3 py-4 text-center text-xs text-gray-500"
            >
              This surface does not expose any custom button slots.
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>