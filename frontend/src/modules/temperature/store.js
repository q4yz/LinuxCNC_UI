// Temperature module Pinia store. Owns the sensor dict, the rolling
// 30 s chart history, the unit toggle, the per-sensor visibility /
// colour maps. Subscribes to ``state.temperatures`` on the event bus
// and mirrors the machine module's telemetry. See ``.agent/STATE.md``
// § 2 (store id), § 3 (event bus), § 9 (active modules table).

import { defineStore, storeToRefs } from "pinia";
import { onScopeDispose, ref } from "vue";

import manifest from "./manifest.js";
import { eventBus } from "../../core/modules/event-bus.js";
import { createModuleSettings } from "../../core/modules/settings.js";

// Chart is locked to a fixed 30 s window of 1 s ticks. The
// ``history_window_seconds`` / ``history_poll_interval_ms`` knobs
// were removed because they were never honoured by the chart.
const WINDOW_SECONDS = 30;
const DEFAULT_POLL_MS = 1_000;
// Purple — used when the backend introduces a sensor the frontend
// has no colour for yet.
const FALLBACK_COLOR = "#A855F7";
const DEFAULT_SENSOR_COLORS = {
  extruder: "#EF4444",
  bed: "#3B82F6",
  cpu: "#10B981",
};

const TOPIC = "state.temperatures";

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
    let sensorsPollHandle = null;
    let busUnsub = null;
    // Tracks whether the store has been started by ``onLoad`` so
    // hot-reloads / double-mounts don't accumulate intervals.
    let running = false;

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
      // wipe the rest of the palette.
      if (settings.sensor_colors && typeof settings.sensor_colors === "object") {
        const next = { ...DEFAULT_SENSOR_COLORS, ...sensorColors.value };
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
      // Fetch sensor state immediately so the chart isn't empty on
      // first render, then poll at the configured cadence.
      refreshSensors();
      sensorsPollHandle = setInterval(refreshSensors, pollMs.value);
      // Push a history point immediately so the chart has data,
      // then roll forward at the same cadence.
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
     * Called by the machine module via the event bus. Accepts the
     * sensors endpoint shape, the legacy ``temperatures`` wrapper,
     * or a raw sensors dict.
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
     * Pull the live sensor state from the backend. The
     * ``GET /api/v1/modules/temperature/sensors`` endpoint returns
     * ``{ sensors: { extruder: { actual, target }, ... } }`` — the
     * canonical source of truth for the chart. The lower-latency
     * WebSocket bridge will replace this poll when available.
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

    // The bus delivers deep-frozen payloads; we deep-clone before
    // storing. See ``.agent/STATE.md`` § 3.
    busUnsub = eventBus.subscribe(TOPIC, (_topic, payload) => {
      ingest(payload);
    });

    // Read settings once at boot. The user changes ``unit`` /
    // ``sensor_colors`` from the Settings UI, which calls
    // ``refreshSettings`` explicitly after a successful PUT.
    refreshSettings();

    // Auto-stop when the pinia scope goes away (component unmount,
    // app teardown) so the polling interval cannot leak across
    // navigation. See ``.agent/STATE.md`` § 10.
    onScopeDispose(() => {
      stop();
      if (busUnsub) {
        busUnsub();
        busUnsub = null;
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
