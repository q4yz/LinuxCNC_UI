import { defineStore } from "pinia";
import { ref } from "vue";

import manifest from "./manifest.js";
import { createModuleSettings } from "../../core/modules/settings.js";

// One transport-level client for the canonical settings endpoints
// (hand-rolled ``fetch`` per .agent/STATE.md § 5).
//
// Persistence contract:
//   * On boot the store reads ``GET /api/v1/modules/camera/settings``
//     and copies ``preferences`` into the reactive ref. Until that
//     read resolves ``preferencesHydrated === false`` so the Settings
//     panel can render a placeholder instead of flashing the
//     hardware-reported names.
//   * Per-camera edits flow through ``updatePreference`` with an
//     optimistic in-memory update. A trailing 400 ms debounce fires
//     a single ``PUT /api/v1/modules/camera/settings`` with the full
//     map (the canonical settings store does not expose partial
//     writes for nested maps).
//   * On unmount the pending PUT is flushed so a 399 ms-old rename
//     is not lost when the operator navigates away.
const STORE_ID = `module_${manifest.id}`;
const DEVICES_URL = "/api/v1/modules/camera/devices";
const PREFERENCE_DEBOUNCE_MS = 400;

// Field set the frontend lets operators touch. ``custom_name`` matches
// the backend snake_case schema; the local ref keeps it as
// ``customName`` for ergonomics in components and the inverse mapping
// happens inside ``_serializePreferences`` / ``_deserializePreferences``.
const EDITABLE_KEYS = new Set(["customName", "flip", "mirror", "hidden"]);

/**
 * @typedef {Object} CameraDevice
 * @property {string} id
 * @property {string} name
 * @property {string} source
 */

/**
 * @typedef {Object} CameraPreference
 * @property {string}  customName
 * @property {boolean} flip
 * @property {boolean} mirror
 * @property {boolean} hidden
 */

/** @returns {CameraPreference} */
function defaultPreference() {
  return {
    customName: "",
    flip: false,
    mirror: false,
    hidden: false,
  };
}

/**
 * @param {*} value
 * @returns {CameraPreference}
 */
function coercePreference(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return defaultPreference();
  }
  return {
    customName: typeof value.customName === "string" ? value.customName : "",
    flip: value.flip === true,
    mirror: value.mirror === true,
    hidden: value.hidden === true,
  };
}

/**
 * @param {Record<string, CameraPreference>} prefs
 * @returns {Record<string, {custom_name: string, flip: boolean, mirror: boolean, hidden: boolean}>}
 */
function serializePreferences(prefs) {
  /** @type {Record<string, ReturnType<typeof serializePreferences>[string]>} */
  const out = {};
  if (!prefs || typeof prefs !== "object") return out;
  for (const [id, pref] of Object.entries(prefs)) {
    if (!id || !pref || typeof pref !== "object") continue;
    out[id] = {
      custom_name:
        typeof pref.customName === "string" ? pref.customName : "",
      flip: pref.flip === true,
      mirror: pref.mirror === true,
      hidden: pref.hidden === true,
    };
  }
  return out;
}

/**
 * @param {*} value
 * @returns {Record<string, CameraPreference>}
 */
function deserializePreferences(value) {
  /** @type {Record<string, CameraPreference>} */
  const out = {};
  if (!value || typeof value !== "object" || Array.isArray(value)) return out;
  for (const [id, raw] of Object.entries(value)) {
    if (!id || typeof id !== "string") continue;
    out[id] = coercePreference(raw);
  }
  return out;
}

export const useCameraStore = defineStore(STORE_ID, () => {
  // Lazy settings client. Same singleton pattern as temperature/store.js:
  // a unit test that mounts Pinia without the registry never trips.
  const settings = createModuleSettings(manifest.id);

  /** @type {import("vue").Ref<CameraDevice[]>} */
  const devices = ref([]);
  const activeCameraId = ref("");
  /** @type {import("vue").Ref<Record<string, CameraPreference>>} */
  const cameraPreferences = ref({});
  const preferencesHydrated = ref(false);
  const isLoading = ref(false);
  const error = ref("");

  let debounceTimer = null;
  let pendingSnapshot = null;
  let inflightWrite = null;

  function writeNow() {
    if (!pendingSnapshot) return;
    const snapshot = pendingSnapshot;
    pendingSnapshot = null;
    if (debounceTimer) {
      clearTimeout(debounceTimer);
      debounceTimer = null;
    }
    inflightWrite = settings.writeAll({
      preferences: serializePreferences(snapshot),
    });
    inflightWrite
      .catch((requestError) => {
        // eslint-disable-next-line no-console
        console.error("[camera] failed to persist preferences:", requestError);
      })
      .finally(() => {
        inflightWrite = null;
      });
  }

  /**
   * Flush a pending debounced PUT immediately. Call this from
   * ``onBeforeUnmount`` so a 399 ms-old rename survives a page
   * navigation.
   *
   * @returns {Promise<void>}
   */
  async function flushPendingPreferenceWrite() {
    if (inflightWrite) {
      try {
        await inflightWrite;
      } catch (_) {
        // Errors are already logged in ``writeNow``.
      }
    }
    if (pendingSnapshot) {
      writeNow();
      if (inflightWrite) {
        try {
          await inflightWrite;
        } catch (_) {
          /* logged */
        }
      }
    }
  }

  async function fetchDevices() {
    isLoading.value = true;
    error.value = "";

    try {
      const response = await fetch(DEVICES_URL);
      if (!response.ok) {
        throw new Error(
          `Camera device request failed: ${response.status} ${response.statusText}`,
        );
      }

      const payload = await response.json();
      if (!Array.isArray(payload?.devices)) {
        throw new Error("Camera device response did not contain a devices list");
      }

      devices.value = payload.devices
        .filter((device) => device && typeof device.id === "string" && device.id)
        .map((device) => ({
          id: device.id,
          name:
            typeof device.name === "string" && device.name
              ? device.name
              : device.id,
          source: typeof device.source === "string" ? device.source : "unknown",
        }));

      // ``hydratePreferences`` runs in the background; the device list
      // is independent from the preferences so we surface the cameras
      // immediately instead of blocking on the settings round-trip.
      void hydratePreferences();

      if (!devices.value.some((device) => device.id === activeCameraId.value)) {
        activeCameraId.value = devices.value[0]?.id ?? "";
      }
      return true;
    } catch (requestError) {
      error.value =
        requestError instanceof Error
          ? requestError.message
          : "Unable to load camera devices";
      return false;
    } finally {
      isLoading.value = false;
    }
  }

  /**
   * Populate ``cameraPreferences`` from the backend ``settings.json``
   * payload. Called from ``fetchDevices``; idempotent.
   */
  async function hydratePreferences() {
    try {
      const payload = await settings.readAll();
      cameraPreferences.value = deserializePreferences(payload?.preferences);
      preferencesHydrated.value = true;
    } catch (requestError) {
      // eslint-disable-next-line no-console
      console.error("[camera] failed to load preferences:", requestError);
      preferencesHydrated.value = true; // unblock the UI even on failure
    }
  }

  /**
   * Visible cameras only — the helper used by ``cycleCamera`` and by
   * the Watcher in ``CameraViewer`` that auto-steps past a hidden
   * active camera.
   *
   * @returns {CameraDevice[]}
   */
  function visibleDevices() {
    return devices.value.filter(
      (device) => cameraPreferences.value[device.id]?.hidden !== true,
    );
  }

  function cycleCamera() {
    const visible = visibleDevices();
    if (visible.length === 0) {
      activeCameraId.value = "";
      return;
    }

    const currentIndex = visible.findIndex(
      (device) => device.id === activeCameraId.value,
    );
    const nextIndex = currentIndex < 0 ? 0 : (currentIndex + 1) % visible.length;
    activeCameraId.value = visible[nextIndex].id;
  }

  /**
   * Update one field of one camera's preferences. The in-memory ref
   * changes synchronously so the UI does not wait for the network;
   * the backend write is debounced 400 ms.
   *
   * @param {string} id
   * @param {"customName"|"flip"|"mirror"|"hidden"} key
   * @param {string|boolean} value
   */
  function updatePreference(id, key, value) {
    if (!id || !EDITABLE_KEYS.has(key)) return;
    if (
      (key === "flip" || key === "mirror" || key === "hidden") &&
      typeof value !== "boolean"
    ) {
      return;
    }
    if (key === "customName" && typeof value !== "string") return;

    const current = cameraPreferences.value[id] ?? defaultPreference();
    const next = { ...defaultPreference(), ...current, [key]: value };
    cameraPreferences.value = {
      ...cameraPreferences.value,
      [id]: next,
    };

    pendingSnapshot = cameraPreferences.value;
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(writeNow, PREFERENCE_DEBOUNCE_MS);
  }

  return {
    devices,
    activeCameraId,
    cameraPreferences,
    preferencesHydrated,
    isLoading,
    error,
    visibleDevices,
    fetchDevices,
    hydratePreferences,
    cycleCamera,
    updatePreference,
    flushPendingPreferenceWrite,
  };
});
