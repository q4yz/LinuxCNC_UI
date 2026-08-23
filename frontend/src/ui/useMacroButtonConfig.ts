// Shared "macro button config" composable.
//
// Reads / writes the ``macroButtons`` array against the per-module
// settings store (the canonical
// ``createModuleSettings(moduleId).readKey(...)`` /
// ``writeKey(...)`` endpoints exposed by the backend's
// ``SettingsStore``). The composable normalises a missing /
// corrupt key to ``[]`` so a host component can render one of the
// per-slot entries with a simple lookup and never crash on first
// boot.
//
// Why a composable rather than letting each host talk to the
// settings client directly? Three reasons:
//
//   * One place that defines the wire shape (``macroButtons``) so
//     a future rename touches one file.
//   * ``buttonsBySlot`` memoises a slot → descriptor lookup,
//     saving host components from filtering the array themselves.
//   * ``persist`` returns a single Promise so the editor's
//     ``update:modelValue`` can fire-and-forget without each host
//     having to reimplement the read-modify-write cycle.
//
// Backend-side schema note: the backend Pydantic ``MachineSettings``
// and ``CameraSettings`` models will gain a ``macroButtons`` field
// with default ``[]`` to round-trip the schema through
// ``SettingsStore``. Frontend is defensive: if the server returns
// ``null`` / ``undefined`` we coerce to ``[]``.

import { computed, ref } from "vue";

import { createModuleSettings } from "../core/modules/settings";

const SETTINGS_KEY = "macroButtons";

/**
 * Coerce a server response into the canonical
 * ``MacroButtonDescriptor[]`` shape.
 *
 * @param {unknown} raw
 * @returns {Array<object>}
 */
function normalise(raw) {
  if (!Array.isArray(raw)) return [];
  return raw.filter(
    (row) =>
      row !== null &&
      typeof row === "object" &&
      typeof row.slot === "string",
  );
}

/**
 * Build a config client scoped to ``moduleId``.
 *
 * @param {string} moduleId
 * @returns {{
 *   buttons: import('vue').Ref<Array<object>>,
 *   buttonsBySlot: import('vue').ComputedRef<Record<string, object | undefined>>,
 *   loading: import('vue').Ref<boolean>,
 *   error: import('vue').Ref<string>,
 *   refresh: () => Promise<void>,
 *   persist: (next: Array<object>) => Promise<void>,
 * }}
 */
export function useMacroButtonConfig(moduleId) {
  const client = createModuleSettings(moduleId);
  const buttons = ref([]);
  const loading = ref(false);
  const error = ref("");

  const buttonsBySlot = computed(() => {
    const map = {};
    for (const row of buttons.value) {
      map[row.slot] = row;
    }
    return map;
  });

  async function refresh() {
    loading.value = true;
    error.value = "";
    try {
      const raw = await client.readKey(SETTINGS_KEY);
      buttons.value = normalise(raw);
    } catch (requestError) {
      error.value =
        requestError instanceof Error
          ? requestError.message
          : `Failed to load macroButtons for ${moduleId}`;
      buttons.value = [];
    } finally {
      loading.value = false;
    }
  }

  async function persist(next) {
    // ``persist`` deliberately does NOT mutate ``buttons.value``.
    // The earlier implementation wrote back into the local cache,
    // which re-fired every ``watch(() => buttons.value, ...)``
    // deep-watcher in the host (e.g. ``MachineSettingsPanel.vue``)
    // and produced the request spam observed at first ship. The
    // host owns ``buttons.value``; the editor's emit is the only
    // path that should change it.
    const safe = normalise(next);
    error.value = "";
    try {
      await client.writeKey(SETTINGS_KEY, safe);
    } catch (requestError) {
      error.value =
        requestError instanceof Error
          ? requestError.message
          : `Failed to save macroButtons for ${moduleId}`;
      // Surface but do not throw — the editor mutates locally and
      // a transient write failure should not crash the host.
    }
  }

  return {
    buttons,
    buttonsBySlot,
    loading,
    error,
    refresh,
    persist,
  };
}

export default useMacroButtonConfig;