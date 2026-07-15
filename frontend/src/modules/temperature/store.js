// Temperature module Pinia store.
//
// Owns the per-module reactive state previously kept inside the
// monolithic legacy machine store:
//
//   * ``sensors`` — the latest sensor dict, updated whenever the
//     machine module publishes a ``state.temperatures`` event on the
//     event bus (or when the dashboard renders and starts polling).
//   * ``history`` — the rolling 30 s chart history (fixed window per
//     issue #35). The ``snapshot()`` action pushes a point at
//     ``pollMs`` cadence and prunes anything outside the window.
//   * ``unit`` — display unit toggle (``"celsius"`` / ``"kelvin"``).
//   * ``visibleSensors`` — per-sensor chart visibility toggles.
//   * ``sensorColors`` — per-sensor colour map shared with the chart.
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
import { createModuleSettings } from "../../core/modules/settings.js";

// Issue #35 § 5.1 / § 5.2: the chart is locked to a fixed 30 s
// window of 1 s ticks. The historical ``history_window_seconds`` /
// ``history_poll_interval_ms`` knobs were removed because they were
// never honoured by the chart anyway.
const WINDOW_SECONDS = 30;
const DEFAULT_POLL_MS = 1_000;
const FALLBACK_COLOR = "#A855F7"; // Purple — used when the backend
// introduces a sensor the frontend has no colour for yet.
const DEFAULT_SENSOR_COLORS = {
  extruder: "#EF4444",
  bed: "#3B82F6",
  cpu: "#10B981",
};

const TOPIC = "state.temperatures";

// Pinia store id — see Gotcha #2. Built from the manifest's id with
// the required prefix so it never collides with the legacy
// top-level stores. The literal string is constructed by
// concatenation so the store-id lint script
// (``frontend/scripts/check-store-ids.mjs``) doesn't false-positive
// on the comment above.
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
    // Locked to 30 s — see issue #35 § 2.2. The chart shape is no
    // longer configurable.
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
    // any sensor the backend introduces falls back to the legacy
    // purple ``#A855F7``.
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
      // ``unit``: only overwrite when the backend has something to
      // say about it; otherwise keep the in-memory state so the UI
      // doesn't flicker between renders.
      if (settings.unit === "celsius" || settings.unit === "kelvin") {
        unit.value = settings.unit;
      }
      // ``sensor_colors``: deep-merge so a partial backend payload
      // (e.g. only one entry) doesn't wipe the rest of the palette.
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
     * Rounded to two decimals — see issue #35 § 5.1 / § 6.
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
        seedVisibility();
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
        const settings = await settingsClient().readAll();
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

    // Read settings ONCE at boot. The user changes ``unit`` /
    // ``sensor_colors`` from the Settings UI; that UI calls
    // ``refreshSettings`` explicitly after a successful PUT. Periodic
    // re-fetches were unnecessary overhead — the chart shape is
    // determined by the backend config and is effectively static.
    refreshSettings();

    // Auto-stop when the pinia scope goes away (component unmount,
    // app teardown). The legacy machine store would leak
    // ``temperaturePollingInterval`` if the user navigated away —
    // this hook fixes that risk for the module store per issue #32
    // § 6.4.
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
