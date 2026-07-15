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
// may receive a smaller or larger ``history_window_seconds`` from
// the settings endpoint, in which case the new value wins.
const DEFAULT_WINDOW_MS = 10_000;
const DEFAULT_POLL_MS = 1_000;
const SETTINGS_REFRESH_MS = 5_000;

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
    let settingsTimer = null;
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
      // Push a point immediately so the chart isn't empty on first
      // render, then poll at the configured cadence.
      snapshot();
      pollHandle = setInterval(snapshot, pollMs.value);
    }

    function stop() {
      running = false;
      if (pollHandle !== null) {
        clearInterval(pollHandle);
        pollHandle = null;
      }
      if (settingsTimer !== null) {
        clearInterval(settingsTimer);
        settingsTimer = null;
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
      const next = payload.temperatures
        ? payload.temperatures
        : payload;
      if (next && typeof next === "object") {
        sensors.value = clone(next);
      }
    }

    /**
     * Read the settings endpoint once and apply. Exposed so the
     * dashboard can refresh after a settings change without waiting
     * for the next periodic tick.
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

    // Wire the bus subscriber once per module lifecycle. The bus
    // delivers deep-frozen payloads; we deep-clone before storing
    // (see Gotcha #3).
    busUnsub = eventBus.subscribe(TOPIC, (_topic, payload) => {
      ingest(payload);
    });

    // Refresh settings periodically; the user can change
    // ``history_window_seconds`` from the Settings UI while the
    // dashboard is open.
    refreshSettings();
    settingsTimer = setInterval(refreshSettings, SETTINGS_REFRESH_MS);

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
