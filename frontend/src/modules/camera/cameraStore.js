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
//     optimistic in-memory update and an immediate PUT. Writes are
//     **serialised through the ``writePreferences`` chain** — every
//     rapid keystroke queues on the previous write's promise tail
//     so the server receives them in order and never overlaps on the
//     wire. A previous debounce was removed because a single
//     operator typing into a single form never produced bursts of
//     writes worth coalescing.
//   * ``deleteIpCamera`` clears the configured ``ip_camera_url`` AND
//     drops the camera's preference row in a single ``writeAll`` so
//     the device list, the persisted settings, and the in-memory
//     cache stay in lock-step. Without this the custom-name row for
//     the removed URL would orphan in the preferences map forever.
//   * On unmount the in-flight write is awaited via
//     ``awaitInFlightPreferenceWrite`` so the most recent keystroke
//     survives page navigation.
const STORE_ID = `module_${manifest.id}`;
const DEVICES_URL = "/api/v1/modules/camera/devices";
const STATUS_URL = "/api/v1/modules/camera/status";

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
  // The backend Pydantic model serialises the operator-facing
  // custom-name field as ``custom_name`` (snake_case). The legacy
  // version of this helper read ``value.customName`` and silently
  // dropped the value to ``""`` on every reload, which made the
  // operator think their custom name was never persisted even
  // though it was sitting on disk in snake_case form.
  return {
    customName: typeof value.custom_name === "string" ? value.custom_name : "",
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
  /**
   * Operator-facing diagnostic from ``GET /status``. Empty when the
   * stream is healthy; carries a single-line English hint when the
   * backend cannot serve the stream (``ustreamer`` not installed,
   * device unplugged, platform unsupported, etc.). The CameraViewer
   * renders this verbatim so an operator on a misconfigured host sees
   * a "this is a dependency problem" message rather than a silent
   * broken image.
   *
   * @type {import("vue").Ref<string>}
   */
  const streamMessage = ref("");
  // The last diagnostic string that was forwarded to the console
  // store. The store only emits a new console row when the message
  // changes, so a periodic refresh does not spam the operator console.
  let lastReportedStreamMessage = "";

  // Serialised PUT chain — every write chains off the previous one
  // so rapid keystrokes never overlap on the wire and the server
  // receives them in the order the operator typed them. Replaces
  // the earlier 400 ms debounce + ``inflightWrite`` pair.
  let currentWrite = Promise.resolve();

  /**
   * Persist a snapshot of the preferences map. Returns the in-flight
   * promise so callers can ``await`` if they need a barrier.
   *
   * @param {Record<string, CameraPreference>} snapshot
   */
  function writePreferences(snapshot) {
    const next = currentWrite
      .catch(() => undefined)
      .then(() =>
        settings.writeAll({ preferences: serializePreferences(snapshot) }),
      );
    currentWrite = next.catch(() => undefined);
    return next;
  }

  /**
   * Await any in-flight preference write so a navigation away does
   * not lose the most recent keystroke. Thin wrapper over the shared
   * ``currentWrite`` chain.
   *
   * @returns {Promise<void>}
   */
  async function awaitInFlightPreferenceWrite() {
    try {
      await currentWrite;
    } catch (_) {
      // Errors are already logged inside ``writePreferences``.
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

      // Refresh the diagnostic message in parallel so the viewer
      // surfaces dependency problems without waiting on a stream
      // error.
      void refreshStreamMessage();

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
      // Fold orphaned preference keys back into the device list as
      // ``historical`` rows so the operator can keep editing their
      // custom names / orientation / hide flags for cameras that
      // are no longer the configured ``ip_camera_url``.
      mergeStoredCamerasIntoDevices();
    } catch (requestError) {
      // eslint-disable-next-line no-console
      console.error("[camera] failed to load preferences:", requestError);
      preferencesHydrated.value = true; // unblock the UI even on failure
    }
  }

  /**
   * Refresh ``streamMessage`` from ``GET /status``. Idempotent; safe
   * to call from the viewer's ``onerror`` handler and from the device
   * refresh path. Emits a single console-store row per distinct
   * diagnostic value so a periodic refresh does not spam the operator
   * console.
   *
   * @returns {Promise<string>} The new ``message`` (empty when healthy).
   */
  async function refreshStreamMessage() {
    try {
      const response = await fetch(STATUS_URL);
      if (!response.ok) {
        throw new Error(
          `Camera status request failed: ${response.status} ${response.statusText}`,
        );
      }
      const payload = await response.json();
      const message =
        typeof payload?.message === "string" ? payload.message : "";
      streamMessage.value = message;
      if (message && message !== lastReportedStreamMessage) {
        lastReportedStreamMessage = message;
        // Lazy import — see ``.agent/context/LESSONS_LEARNED.md`` § 2.4.
        const { useConsoleStore } = await import("../../stores/console.js");
        useConsoleStore().error(`[camera] ${message}`);
      } else if (!message) {
        // Reset the dedup tracker once the supervisor reports healthy
        // so a future recurrence of the same message is logged again.
        lastReportedStreamMessage = "";
      }
      return message;
    } catch (requestError) {
      // Network failure is itself a useful diagnostic; surface a
      // single message and let the user click "Re-check" to retry.
      const message =
        requestError instanceof Error
          ? requestError.message
          : "Unable to reach the camera supervisor.";
      streamMessage.value = message;
      if (message !== lastReportedStreamMessage) {
        lastReportedStreamMessage = message;
        const { useConsoleStore } = await import("../../stores/console.js");
        useConsoleStore().error(`[camera] ${message}`);
      }
      return message;
    }
  }

  /**
   * Add a synthetic entry for every preference key that is not
   * already present in ``devices.value``.
   *
   * The ``/devices`` endpoint enumerates only the *current*
   * ``ip_camera_url`` plus USB cameras. Whenever the operator
   * changes the URL, the previous key stays in ``settings.json``
   * (the operator's custom name persists) but disappears from the
   * live enumeration. Folding the orphaned keys back into
   * ``devices.value`` keeps the settings panel usable — the
   * operator can keep editing custom names, toggle flip/mirror,
   * or remove the orphan entirely.
   *
   * Every stored camera — including orphaned IP URLs from prior
   * sessions — is cycleable. If the upstream is unreachable when
   * the operator picks one, the supervisor's diagnostic panel
   * surfaces the reason (same as for any other reachable-but-broken
   * upstream).
   */
  function mergeStoredCamerasIntoDevices() {
    const known = new Set(devices.value.map((d) => d.id));
    const additions = [];
    for (const [id, pref] of Object.entries(cameraPreferences.value || {})) {
      if (id && !known.has(id)) {
        additions.push({
          id,
          name: id,
          source: "ip",
        });
      }
    }
    if (additions.length > 0) {
      devices.value = [...devices.value, ...additions];
    }
  }

  /**
   * Visible cameras only — the helper used by ``cycleCamera`` and by
   * the Watcher in ``CameraViewer`` that auto-steps past a hidden
   * active camera.
   *
   * Operators can cycle through every stored camera (USB + active
   * IP cam + stored IP URLs from prior sessions). ``hidden`` is the
   * only filter — operators who don't want a camera in their cycle
   * opt out via the "Hide from cycle" checkbox in the settings
   * panel. The previous offline-style filter on stored IP cams
   * was removed so a user can view any camera they have
   * configured.
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
   * the backend write fires immediately and is serialised through the
   * shared ``writePreferences`` chain so two rapid keystrokes never
   * overlap on the wire.
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

    writePreferences(cameraPreferences.value).catch((writeError) => {
      // eslint-disable-next-line no-console
      console.error("[camera] failed to persist preferences:", writeError);
    });
  }

  /**
   * Remove an IP camera entry and drop its preference row in one
   * round-trip so the persisted ``preferences`` map never orphans
   * the removed camera's custom name.
   *
   * The store refuses non-IP callers and returns ``false`` rather
   * than touching the URL — USB cameras must not be removable from
   * this surface.
   *
   * The deleted device may be the currently-configured IP camera
   * URL (live row) or a stored preference for an old URL. The
   * action reads the active URL before deciding whether to clear
   * it, so removing a non-active row is URL-safe.
   *
   * @param {CameraDevice} device
   * @returns {Promise<boolean>}
   */
  async function deleteIpCamera(device) {
    if (!device || device.source !== "ip") {
      // eslint-disable-next-line no-console
      console.warn("[camera] deleteIpCamera called on non-IP device:", device);
      return false;
    }
    try {
      const next = { ...cameraPreferences.value };
      delete next[device.id];
      cameraPreferences.value = next;
      // Read the current settings once so we can decide whether the
      // device being deleted is the currently-configured IP camera
      // URL. If it is, clear the URL; otherwise preserve it so the
      // live stream keeps working through the cleanup round-trip.
      const current = await settings.readAll();
      const isCurrentIpCam = current?.ip_camera_url === device.id;
      const updatePayload = {
        preferences: serializePreferences(next),
        ip_camera_url: isCurrentIpCam
          ? ""
          : typeof current?.ip_camera_url === "string"
            ? current.ip_camera_url
            : "",
      };
      await settings.writeAll(updatePayload);
      // Re-fetch so /devices drops the IP row. ``fetchDevices`` also
      // steps the active camera off the removed device id and
      // re-runs ``mergeStoredCamerasIntoDevices`` (via
      // ``hydratePreferences``) so any synthetic row that no longer
      // has a preference disappears on the next render.
      await fetchDevices();
      return true;
    } catch (requestError) {
      // eslint-disable-next-line no-console
      console.error("[camera] failed to delete IP camera:", requestError);
      error.value =
        requestError instanceof Error
          ? requestError.message
          : "Unable to delete IP camera";
      return false;
    }
  }

  return {
    devices,
    activeCameraId,
    cameraPreferences,
    preferencesHydrated,
    isLoading,
    error,
    streamMessage,
    visibleDevices,
    fetchDevices,
    hydratePreferences,
    cycleCamera,
    updatePreference,
    deleteIpCamera,
    awaitInFlightPreferenceWrite,
    refreshStreamMessage,
  };
});
