// Temperature module Pinia store. Owns the sensor dict, the rolling
// 30 s chart history, the unit toggle, the per-sensor visibility /
// colour maps. Reads sensors from the shared base-thread snapshot
// (``stores/baseThread.js``) so the dashboard only issues one
// HTTP request per second for every slow stream. The historical
// ``state.temperatures`` event-bus topic from the WebSocket is
// gone — the WebSocket now only carries the time-critical fields.
// See ``.agent/STATE.md`` § 2 (store id), § 3 (event bus), § 9
// (active modules table).

import { defineStore, storeToRefs } from "pinia";
import { onScopeDispose, ref, watch } from "vue";

import manifest from "./manifest.js";
import { createModuleSettings } from "../../core/modules/settings.js";
import { useBaseThreadStore } from "../../stores/baseThread.js";

// Chart is locked to a fixed 30 s window of 1 s ticks. The
// ``history_window_seconds`` / ``history_poll_interval_ms`` knobs
// were removed because they were never honoured by the chart.
const WINDOW_SECONDS = 30;
const DEFAULT_POLL_MS = 1_000;
// Purple — used when the backend introduces a sensor the frontend
// has no colour for yet. Stays as the persistent fallback for
// any sensor whose persisted colour was deleted or whose operator
// never set one (see issue #97).
const FALLBACK_COLOR = "#A855F7";
// Issue #97: sensor list is now driven entirely by the backend's
// ``hardware.json`` payload — no hard-coded ``extruder/bed/cpu``
// fixtures. The backend's settings layer seeds the colour map
// deterministically per active heater list. New colours the
// backend adds after the operator's last PUT show up via the
// ``sensor_colors`` merge below.
const DEFAULT_SENSOR_COLORS = {};

// ``module_`` prefix prevents collisions with legacy top-level
// stores. See ``.agent/STATE.md`` § 2.
const STORE_ID = `module_${manifest.id}`;

// Singleton settings client for the canonical four-endpoint
// settings surface. Created lazily so a missing module store (e.g.
// a unit test that mounts Pinia but no event bus) never trips the
// registry bootstrap order.
let settingsClientSingleton = null;
function settingsClient() {
  if (!settingsClientSingleton) {
    settingsClientSingleton = createModuleSettings(manifest.id);
  }
  return settingsClientSingleton;
}

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

function roundTo(value, decimals) {
  if (!Number.isFinite(value)) return 0;
  const factor = Math.pow(10, decimals);
  return Math.round(value * factor) / factor;
}

export const useTemperatureStore = defineStore(
  STORE_ID,
  () => {
    // --- reactive state ------------------------------------------- //
    const sensors = ref({});
    const history = ref([]);
    // Locked to 30 s — chart shape is no longer configurable.
    const windowMs = ref(WINDOW_SECONDS * 1000);
    const pollMs = ref(DEFAULT_POLL_MS);
    // Display unit. Backed by ``settings.unit``; flips the
    // chart Y-axis and the control-box labels without touching the
    // raw value.
    const unit = ref("celsius");
    // Per-sensor chart-visibility toggle. Defaults to true on first
    // sighting.
    const visibleSensors = ref({});
    // Per-sensor colour. Sourced from ``settings.sensor_colors``;
    // Sensors introduced after this palette falls back to the
    // purple sentinel colour.
    const sensorColors = ref({ ...DEFAULT_SENSOR_COLORS });

    // --- non-reactive handles ------------------------------------- //
    let pollHandle = null;
    // Tracks whether the store has been started by ``onLoad`` so
    // hot-reloads / double-mounts don't accumulate intervals.
    let running = false;
    // Stop handle for the base-thread sensors watcher — set when
    // ``start`` mounts it and cleared by ``onScopeDispose``.
    let stopSensorWatch = null;

    // --- helpers -------------------------------------------------- //

    function seedVisibility() {
      const next = {};
      for (const name of Object.keys(sensors.value || {})) {
        if (typeof visibleSensors.value[name] === "boolean") {
          next[name] = visibleSensors.value[name];
        } else {
          next[name] = true;
        }
      }
      visibleSensors.value = next;
    }

    function applySettings(settings) {
      if (!settings || typeof settings !== "object") return;
      // Only overwrite ``unit`` when the backend has something to
      // say about it; otherwise keep the in-memory state so the UI
      // doesn't flicker between renders.
      if (settings.unit === "celsius" || settings.unit === "kelvin") {
        unit.value = settings.unit;
      }
      // Deep-merge ``sensor_colors`` so a partial payload doesn't
      // wipe the rest of the palette. We start from the existing
      // ``sensorColors.value`` so the backend's seeded colours
      // (which arrive on the first ``refreshSettings`` call) are
      // preserved on every subsequent merge. ``DEFAULT_SENSOR_COLORS``
      // is intentionally empty — overlaying it first would discard
      // the seeds and leave the operator with the purple fallback.
      if (settings.sensor_colors && typeof settings.sensor_colors === "object") {
        const next = { ...sensorColors.value };
        for (const [name, hex] of Object.entries(settings.sensor_colors)) {
          if (typeof hex === "string" && /^#[0-9A-Fa-f]{6}$/.test(hex)) {
            next[name] = hex;
          }
        }
        sensorColors.value = next;
      }
    }

    /**
     * Format a Celsius value for display in the active unit.
     * Rounded to two decimals.
     *
     * @param {number|null|undefined} celsius
     * @returns {number}
     */
    function displayTemp(celsius) {
      if (!Number.isFinite(celsius)) return 0;
      const value = unit.value === "kelvin" ? celsius + 273.15 : celsius;
      return roundTo(value, 2);
    }

    /**
     * Toggle the display unit. Persists via the backend so the next
     * page reload picks up the same choice.
     *
     * @param {"celsius"|"kelvin"} nextUnit
     */
    async function setUnit(nextUnit) {
      if (nextUnit !== "celsius" && nextUnit !== "kelvin") return;
      if (unit.value === nextUnit) return;
      unit.value = nextUnit;
      try {
        await settingsClient().writeKey("unit", nextUnit);
      } catch (_) {
        // Best-effort — the in-memory state is already updated.
      }
    }

    /**
     * Flip the chart visibility for a single sensor. The control-box
     * row stays rendered so operators can still set the target.
     *
     * @param {string} name
     */
    function toggleSensorVisibility(name) {
      const current = visibleSensors.value[name];
      visibleSensors.value = {
        ...visibleSensors.value,
        [name]: !(current !== false),
      };
    }

    /**
     * Update a sensor's chart + control-box colour. Persists via
     * ``PUT /settings/sensor_colors`` so the choice survives a
     * reload.
     *
     * @param {string} name
     * @param {string} hex
     */
    async function setSensorColor(name, hex) {
      if (!name || typeof name !== "string") return;
      if (typeof hex !== "string" || !/^#[0-9A-Fa-f]{6}$/.test(hex)) return;
      const next = { ...sensorColors.value, [name]: hex };
      sensorColors.value = next;
      try {
        await settingsClient().writeKey("sensor_colors", {
          ...next,
        });
      } catch (_) {
        // Best-effort — the in-memory state is already updated.
      }
    }

    /**
     * Return the colour for ``name`` — defaults to the legacy
     * purple when the backend introduces a sensor the palette
     * doesn't know about.
     *
     * @param {string} name
     */
    function colorFor(name) {
      return sensorColors.value[name] || FALLBACK_COLOR;
    }

    function snapshot() {
      const now = Date.now();
      const date = new Date(now);
      const pad = (n) => n.toString().padStart(2, "0");
      const cents = Math.floor(date.getMilliseconds() / 10);
      const label = `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(
        date.getSeconds(),
      )}.${cents.toString().padStart(2, "0")}`;
      // Deep-clone the frozen payload so the rolling buffer keeps
      // independent copies. See ``.agent/STATE.md`` § 3.
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
      // Sensor reads come from the shared base-thread snapshot
      // (``stores/baseThread.js``), started at app boot. We no
      // longer schedule a ``refreshSensors`` interval here — one
      // HTTP request per second covers every slow stream. The
      // history snapshot still ticks at 1 s so the chart's 30 s
      // rolling window keeps advancing even when no new sensors
      // arrive (the base-thread store fires ``refresh`` every
      // second regardless, but the chart needs its own clock so
      // empty frames still age out).
      snapshot();
      pollHandle = setInterval(snapshot, pollMs.value);
    }

    function stop() {
      running = false;
      if (pollHandle !== null) {
        clearInterval(pollHandle);
        pollHandle = null;
      }
    }

    /**
     * Called by the watcher below when the base-thread snapshot
     * publishes a new ``sensors`` dict. Also exposed publicly so
     * tests / future code can ingest a synthetic payload without
     * waiting for the next tick.
     *
     * @param {*} payload
     */
    function ingest(payload) {
      if (!payload) return;
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
        seedVisibility();
      }
    }

    /**
     * Read the settings endpoint once and apply. Exposed so the
     * dashboard can re-pull after a settings PUT — settings are no
     * longer polled, so this is the only way to pick up changes.
     */
    async function refreshSettings() {
      try {
        const settings = await settingsClient().readAll();
        if (settings) applySettings(settings);
      } catch (_) {
        // Settings are best-effort — fall back to defaults.
      }
    }

    /**
     * Force an out-of-band base-thread refresh. Replaces the old
     * direct ``GET /sensors`` poll — the snapshot endpoint is the
     * canonical source now, so a "refresh sensors" action is just
     * a snapshot refresh. Kept on the public action surface so any
     * future "refresh now" button keeps working.
     */
    async function refreshSensors() {
      await useBaseThreadStore().refresh();
    }

    // Subscribe to the base-thread store's ``sensors`` ref. The
    // base-thread store fires every second; we deep-clone before
    // storing so a downstream mutation cannot leak back into the
    // base-thread store. The watcher is ``deep: true`` so the
    // top-level reassignment inside the baseThread store's
    // ``refresh()`` action reliably fires across module boundaries
    // — Pinia's OPTIONS-API proxy does not always rebroadcast a
    // shallow reassignment to consumers in sibling modules.
    // The payload is a tiny dict (a handful of sensor readings)
    // so the deep-traversal cost is negligible.
    const baseThread = useBaseThreadStore();
    // Pull the current value synchronously so the panel renders
    // populated sensors on the first frame, even if the dashboard
    // mounts before the first 1 Hz tick has landed.
    ingest(baseThread.sensors);
    stopSensorWatch = watch(
      () => baseThread.sensors,
      (next) => {
        if (next && typeof next === "object") {
          ingest(next);
        }
      },
      { immediate: true, deep: true },
    );

    // Read settings once at boot. The user changes ``unit`` /
    // ``sensor_colors`` from the Settings UI, which calls
    // ``refreshSettings`` explicitly after a successful PUT.
    refreshSettings();

    // Auto-stop when the pinia scope goes away (component unmount,
    // app teardown) so the polling interval cannot leak across
    // navigation. See ``.agent/STATE.md`` § 10.
    onScopeDispose(() => {
      stop();
      if (stopSensorWatch) {
        stopSensorWatch();
        stopSensorWatch = null;
      }
    });

    // Public surface.
    return {
      sensors,
      history,
      windowMs,
      pollMs,
      unit,
      visibleSensors,
      sensorColors,
      ingest,
      snapshot,
      start,
      stop,
      refreshSettings,
      refreshSensors,
      displayTemp,
      setUnit,
      toggleSensorVisibility,
      setSensorColor,
      colorFor,
    };
  },
);

/**
 * Convenience wrapper around ``storeToRefs`` so callers can
 * destructure the reactive state without losing reactivity.
 */
export function useTemperatureRefs() {
  const store = useTemperatureStore();
  return { store, ...storeToRefs(store) };
}

export default useTemperatureStore;
