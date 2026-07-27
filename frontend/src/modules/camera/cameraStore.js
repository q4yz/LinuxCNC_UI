import { defineStore } from "pinia";
import { ref } from "vue";

import manifest from "./manifest.js";

const STORE_ID = `module_${manifest.id}`;
const DEVICES_URL = "/api/v1/modules/camera/devices";
const PREFERENCES_STORAGE_KEY = "linuxcnc.camera.preferences";
const PREFERENCE_KEYS = new Set(["flip", "mirror", "customName"]);

/**
 * @typedef {Object} CameraDevice
 * @property {string} id
 * @property {string} name
 * @property {string} source
 */

/**
 * @typedef {Object} CameraPreference
 * @property {boolean} flip
 * @property {boolean} mirror
 * @property {string} customName
 */

/** @returns {CameraPreference} */
function defaultPreference() {
  return {
    flip: false,
    mirror: false,
    customName: "",
  };
}

function availableStorage() {
  try {
    if (typeof window === "undefined") return null;
    return window.localStorage ?? null;
  } catch (_) {
    return null;
  }
}

/**
 * @param {*} value
 * @returns {Record<string, CameraPreference>}
 */
function normalizePreferences(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};

  return Object.fromEntries(
    Object.entries(value)
      .filter(([id, preference]) => {
        return Boolean(id) && preference && typeof preference === "object";
      })
      .map(([id, preference]) => [
        id,
        {
          flip: preference.flip === true,
          mirror: preference.mirror === true,
          customName:
            typeof preference.customName === "string"
              ? preference.customName
              : "",
        },
      ]),
  );
}

/** @returns {Record<string, CameraPreference>} */
function loadPreferences() {
  const storage = availableStorage();
  if (!storage) return {};

  try {
    const serialized = storage.getItem(PREFERENCES_STORAGE_KEY);
    if (!serialized) return {};
    return normalizePreferences(JSON.parse(serialized));
  } catch (_) {
    return {};
  }
}

/** @param {Record<string, CameraPreference>} preferences */
function persistPreferences(preferences) {
  const storage = availableStorage();
  if (!storage) return;

  try {
    storage.setItem(PREFERENCES_STORAGE_KEY, JSON.stringify(preferences));
  } catch (_) {
    // Keep the in-memory preference usable when storage is blocked or full.
  }
}

export const useCameraStore = defineStore(STORE_ID, () => {
  /** @type {import("vue").Ref<CameraDevice[]>} */
  const devices = ref([]);
  const activeCameraId = ref("");
  /** @type {import("vue").Ref<Record<string, CameraPreference>>} */
  const cameraPreferences = ref(loadPreferences());
  const isLoading = ref(false);
  const error = ref("");

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

  function cycleCamera() {
    if (devices.value.length === 0) {
      activeCameraId.value = "";
      return;
    }

    const currentIndex = devices.value.findIndex(
      (device) => device.id === activeCameraId.value,
    );
    const nextIndex = currentIndex < 0 ? 0 : (currentIndex + 1) % devices.value.length;
    activeCameraId.value = devices.value[nextIndex].id;
  }

  /**
   * @param {string} id
   * @param {"flip"|"mirror"|"customName"} key
   * @param {boolean|string} value
   */
  function updatePreference(id, key, value) {
    if (!id || !PREFERENCE_KEYS.has(key)) return;
    if ((key === "flip" || key === "mirror") && typeof value !== "boolean") {
      return;
    }
    if (key === "customName" && typeof value !== "string") return;

    const current = cameraPreferences.value[id] ?? defaultPreference();
    const nextPreference = {
      ...defaultPreference(),
      ...current,
      [key]: value,
    };
    cameraPreferences.value = Object.fromEntries([
      ...Object.entries(cameraPreferences.value),
      [id, nextPreference],
    ]);
    persistPreferences(cameraPreferences.value);
  }

  return {
    devices,
    activeCameraId,
    cameraPreferences,
    isLoading,
    error,
    fetchDevices,
    cycleCamera,
    updatePreference,
  };
});
