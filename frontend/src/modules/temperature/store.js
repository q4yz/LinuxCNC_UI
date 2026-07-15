// Temperature module Pinia store.
//
// Owns the per-module reactive state previously kept inside the
// monolithic legacy machine store:
//
//   * ``sensors`` — the latest sensor dict, updated whenever the
//     machine module publishes a ``state.temperatures`` event on the
//     event bus (or when the dashboard renders and starts polling).
//   * ``history`` — the rolling ``windowMs``-second chart history. The
//     ``snapshot()`` action pushes a point at ``pollMs`` cadence
//     (zero-order hold) and prunes anything older than ``windowMs``.
//
// The store id is namespaced under the ``module_`` prefix per
// ``MODULE_SYSTEM_ROADMAP.md`` § 12 Gotcha #2 so it can never
// collide with the legacy top-level Pinia store id that still
// exists during the migration window.
//
// Reference: ``.agent/contracts/frontend-module.md`` § 5.

import { defineStore, storeToRefs } from "pinia";
import { onScopeDispose, ref } from "vue";

import manifest from "./manifest.js";
import { eventBus } from "../../core/modules/event-bus.js";

// Defaults mirror the backend ``TemperatureSettings`` Pydantic model
// (see ``backend/modules/temperature/settings.py``). The frontend
// receives ``history_window_seconds`` and ``history_poll_interval_ms``
// from the settings endpoint on startup; thereafter those values are
// treated as immutable configuration sourced from the backend.
// Settings are read **once** at boot — the chart shape is fixed by
// the user's config and not something the dashboard needs to
// renegotiate over and over (see issue #32 § 6.6).
const DEFAULT_WINDOW_MS = 10_000;
const DEFAULT_POLL_MS = 1_000;

const TOPIC = "state.temperatures";

// Pinia store id — see Gotcha #2. Built from the manifest's id with
// the required prefix so it never collides with the legacy
// top-level stores. The literal string is constructed by
// concatenation so the store-id lint script
// (``frontend/scripts/check-store-ids.mjs``) doesn't false-positive
// on the comment above.
const STORE_ID = `module_${manifest.id}`;

/**
 * Structured clone for arbitrary JSON-serialisable payloads. Falls
 * back to JSON when ``structuredClone`` isn't available (older
 * browsers, jsdom). The bus already deep-freezes the payload, but we
 * clone before storing in case future publishers hand us mutable
 * references.
 *
 * @param {*} value
 */
function clone(value) {
  if (typeof structuredClone === "function") {
    try {
      return structuredClone(value);
    } catch (_) {
      // Fall through to JSON path.
    }
  }
  return JSON.parse(JSON.stringify(value));
}

export const useTemperatureStore = defineStore(
  STORE_ID,
  () => {
    // --- reactive state ------------------------------------------- //
    const sensors = ref({});
    const history = ref([]);
    // Settings pulled from the backend on first read. We keep the
    // values reactive so the chart window can react to live changes.
    const windowMs = ref(DEFAULT_WINDOW_MS);
    const pollMs = ref(DEFAULT_POLL_MS);

    // --- non-reactive handles ------------------------------------- //
    let pollHandle = null;
    let sensorsPollHandle = null;
    let busUnsub = null;
    // Tracks whether the store has been started by ``onLoad`` so
    // hot-reloads / double-mounts don't accumulate intervals.
    let running = false;

    // --- helpers -------------------------------------------------- //

    function applySettings(settings) {
      if (!settings || typeof settings !== "object") return;
      if (Number.isFinite(settings.history_window_seconds)) {
        windowMs.value = Math.max(1, settings.history_window_seconds) * 1000;
      }
      if (Number.isFinite(settings.history_poll_interval_ms)) {
        pollMs.value = Math.max(100, settings.history_poll_interval_ms);
      }
    }

    function snapshot() {
      const now = Date.now();
      const date = new Date(now);
      const pad = (n) => n.toString().padStart(2, "0");
      const label = `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
      // Deep clone so a frozen payload stays deep-frozen in our
      // rolling buffer; mutating one history point can't corrupt
      // another point's ``sensors`` snapshot.
      history.value.push({
        timestamp: now,
        time: label,
        sensors: clone(sensors.value || {}),
      });
      const cutoff = now - windowMs.value;
      history.value = history.value.filter((p) => p.timestamp >= cutoff);
    }

    function start() {
      if (running) return;
      running = true;
      // Fetch sensor state immediately so the chart isn't empty on
      // first render, then poll at the configured cadence. The state
      // endpoint is the source of truth — we don't rely on the
      // (currently disabled) telemetry WebSocket for chart updates.
      refreshSensors();
      sensorsPollHandle = setInterval(refreshSensors, pollMs.value);
      // Push a history point immediately so the chart has data, then
      // roll forward at the same cadence.
      snapshot();
      pollHandle = setInterval(snapshot, pollMs.value);
    }

    function stop() {
      running = false;
      if (pollHandle !== null) {
        clearInterval(pollHandle);
        pollHandle = null;
      }
      if (sensorsPollHandle !== null) {
        clearInterval(sensorsPollHandle);
        sensorsPollHandle = null;
      }
    }

    /**
     * Called by the machine module via the event bus. Accepts either
     * a ``state.temperatures`` payload (with a ``temperatures`` field)
     * or a raw sensors dict.
     *
     * @param {*} payload
     */
    function ingest(payload) {
      if (!payload) return;
      // Accept three shapes:
      //   1. The temperature sensors endpoint returns
      //      ``{ sensors: { extruder: {...}, ... } }``.
      //   2. The legacy machine module publishes
      //      ``{ temperatures: { ... } }`` on the event bus.
      //   3. Some publishers hand us the raw sensors dict directly.
      let next = payload;
      if (payload.sensors && typeof payload.sensors === "object") {
        next = payload.sensors;
      } else if (
        payload.temperatures &&
        typeof payload.temperatures === "object"
      ) {
        next = payload.temperatures;
      }
      if (next && typeof next === "object") {
        sensors.value = clone(next);
      }
    }

    /**
     * Read the settings endpoint once and apply. Exposed so the
     * dashboard can re-pull after a settings PUT without waiting for
     * any periodic tick — settings are no longer polled, so the only
     * way to pick up changes is to call this explicitly.
     */
    async function refreshSettings() {
      try {
        const settings = await fetch(
          `/api/v1/modules/${manifest.id}/settings`,
        ).then(async (r) => (r.ok ? r.json() : null));
        if (settings) applySettings(settings);
      } catch (_) {
        // Settings are best-effort — fall back to defaults.
      }
    }

    /**
     * Pull the live sensor state from the backend. The backend
     * ``GET /api/v1/modules/temperature/sensors`` returns
     * ``{ sensors: { extruder: { actual, target }, ... } }`` which is
     * the canonical source of truth for the chart. The telemetry
     * WebSocket would be the lower-latency alternative, but it
     * currently 404s because ``websockets`` isn't installed; this
     * poll keeps the UI alive until that bridge lands.
     */
    async function refreshSensors() {
      try {
        const data = await fetch(
          `/api/v1/modules/${manifest.id}/sensors`,
        ).then(async (r) => (r.ok ? r.json() : null));
        if (data) ingest(data);
      } catch (_) {
        // Best-effort — keep the last known sensors visible.
      }
    }

    // Wire the bus subscriber once per module lifecycle. The bus
    // delivers deep-frozen payloads; we deep-clone before storing
    // (see Gotcha #3). This stays as a forward-compatible hook for
    // the eventual telemetry WebSocket bridge.
    busUnsub = eventBus.subscribe(TOPIC, (_topic, payload) => {
      ingest(payload);
    });

    // Read settings ONCE at boot. The user changes ``windowMs`` /
    // ``pollMs`` from the Settings UI; that UI calls
    // ``refreshSettings`` explicitly after a successful PUT. Periodic
    // re-fetches were unnecessary overhead — the chart shape is
    // determined by the backend config and is effectively static.
    refreshSettings();

    // Auto-stop when the pinia scope goes away (component unmount,
    // app teardown). The legacy machine store would leak
    // ``temperaturePollingInterval`` if the user navigated away —
    // this hook fixes that risk for the module store per issue #32
    // § 6.4.
    onScopeDispose(stop);

    // Public surface.
    return {
      sensors,
      history,
      windowMs,
      pollMs,
      ingest,
      snapshot,
      start,
      stop,
      refreshSettings,
      refreshSensors,
    };
  },
);

/**
 * Helper that wraps :func:`storeToRefs` so callers can destructure
 * the reactive state without losing reactivity (per
 * ``AI_INSTRUCTIONS.md`` § 17). Re-exported here so module consumers
 * have a single import surface.
 */
export function useTemperatureRefs() {
  const store = useTemperatureStore();
  return { store, ...storeToRefs(store) };
}

export default useTemperatureStore;
