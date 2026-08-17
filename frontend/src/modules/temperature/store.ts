// Temperature module Pinia store. Owns the sensor / heater set, the
// rolling 30 s chart history, the unit toggle, and the per-entry
// visibility / colour maps.
//
// The store now consumes the **typed entity surface** from the
// base-thread store (``baseThread.readings: ReadingSet``) instead
// of the raw ``sensors`` dict. Wire-shape knowledge lives in the
// ``temperatureMapper`` — this store never branches on
// ``reading.target !== undefined`` to discriminate sensors from
// heaters; ``reading.isControllable`` carries the discriminator.
//
// Writes go through ``temperatureFacade.setTarget`` so the
// legacy ``POST /temperature/sensors/{name}/target`` endpoint is
// never called — that endpoint returns ``410 Gone``. The facade
// routes through the live ``POST /tools/tools/{tool_id}/target``
// endpoint instead.

import { defineStore, storeToRefs } from "pinia";
import { onScopeDispose, ref, watch } from "vue";

import manifest from "./manifest";
import { createModuleSettings } from "../../core/modules/settings";
import { useBaseThreadStore } from "../../stores/baseThread";
import { temperatureFacade } from "../../facades/temperatureFacade";
import { TemperatureUnit } from "../../entities/common/Unit";

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

/**
 * Project a ``ReadingSet`` to the legacy chart-friendly shape
 * ``{ id: { actual, target? } }``. Kept only for the chart's
 * rolling-history buffer (which clones the projection per tick).
 * New consumers should reach for ``readings`` + entity getters.
 */
function readingsToChartShape(readings) {
  const out = {};
  readings.forEach((r) => {
    out[r.id] = {
      actual: r.actualCelsius,
      ...(r.isControllable && { target: r.targetCelsius }),
    };
  });
  return out;
}

export const useTemperatureStore = defineStore(
  STORE_ID,
  () => {
    // --- reactive state ------------------------------------------- //
    /**
     * Live readings mirror (legacy shape — kept for the chart's
     * history buffer). The entity surface is ``readings`` below.
     * @type {import("vue").Ref<Record<string, {actual:number,target?:number}>>}
     */
    const sensors = ref({});
    /** @type {import("vue").Ref<Array<{timestamp:number,time:string,sensors:object}>>} */
    const history = ref([]);
    // Locked to 30 s — chart shape is no longer configurable.
    const windowMs = ref(WINDOW_SECONDS * 1000);
    const pollMs = ref(DEFAULT_POLL_MS);
    // Display unit. Backed by ``settings.unit``; flips the
    // chart Y-axis and the control-box labels without touching the
    // raw value.
    const unit = ref(TemperatureUnit.CELSIUS);
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

    // --- helpers -------------------------------------------------- //

    function seedVisibility(readings) {
      const next = {};
      readings.forEach((r) => {
        if (typeof visibleSensors.value[r.id] === "boolean") {
          next[r.id] = visibleSensors.value[r.id];
        } else {
          next[r.id] = true;
        }
      });
      visibleSensors.value = next;
    }

    function applySettings(settings) {
      if (!settings || typeof settings !== "object") return;
      if (settings.unit === TemperatureUnit.CELSIUS || settings.unit === TemperatureUnit.KELVIN) {
        unit.value = settings.unit;
      }
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
      const value = unit.value === TemperatureUnit.KELVIN ? celsius + 273.15 : celsius;
      return roundTo(value, 2);
    }

    /**
     * Toggle the display unit. Persists via the backend so the next
     * page reload picks up the same choice.
     */
    async function setUnit(nextUnit) {
      if (nextUnit !== TemperatureUnit.CELSIUS && nextUnit !== TemperatureUnit.KELVIN) return;
      if (unit.value === nextUnit) return;
      unit.value = nextUnit;
      try {
        await settingsClient().writeKey("unit", nextUnit);
      } catch (_) {
        // Best-effort — the in-memory state is already updated.
      }
    }

    /**
     * Flip the chart visibility for a single reading.
     */
    function toggleSensorVisibility(name) {
      const current = visibleSensors.value[name];
      visibleSensors.value = {
        ...visibleSensors.value,
        [name]: !(current !== false),
      };
    }

    /**
     * Update a reading's chart + control-box colour. Persists via
     * ``PUT /settings/sensor_colors`` so the choice survives a
     * reload.
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

    /** Return the colour for ``name``; defaults to the purple sentinel. */
    function colorFor(name) {
      return sensorColors.value[name] || FALLBACK_COLOR;
    }

    /**
     * Snapshot the current readings into the rolling history
     * buffer. Stores both the legacy ``{id: {actual, target?}}``
     * shape (for the chart) and the entity surface (future
     * consumers).
     */
    function snapshot() {
      const now = Date.now();
      const date = new Date(now);
      const pad = (n) => n.toString().padStart(2, "0");
      const cents = Math.floor(date.getMilliseconds() / 10);
      const label = `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(
        date.getSeconds(),
      )}.${cents.toString().padStart(2, "0")}`;
      // Deep-clone the frozen payload so the rolling buffer keeps
      // independent copies.
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
     * Ingest a fresh ``ReadingSet`` from the base-thread store.
     * Replaces the legacy ``payload.sensors`` ingest path. Public
     * so tests / synthetic payloads can drive the store without
     * waiting for the next tick.
     */
    function ingest(readings) {
      if (!readings || typeof readings.forEach !== "function") return;
      sensors.value = readingsToChartShape(readings);
      seedVisibility(readings);
    }

    /**
     * Set the target temperature for a heater. Routes through the
     * facade so the legacy 410 endpoint is never called.
     */
    async function setTarget(toolId, target) {
      const result = await temperatureFacade.setTarget(toolId, target);
      return result;
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
     * canonical source now.
     */
    async function refreshSensors() {
      await useBaseThreadStore().refresh();
    }

    // --- base-thread consumer -------------------------------------- //
    const baseThread = useBaseThreadStore();
    // Pull the current entity state synchronously so the panel
    // renders populated sensors on the first frame.
    ingest(baseThread.readings);
    const stopReadingsWatch = watch(
      () => baseThread.readings,
      (next) => {
        if (next && typeof next.forEach === "function") {
          ingest(next);
        }
      },
      { immediate: true, deep: true },
    );

    refreshSettings();

    onScopeDispose(() => {
      stop();
      if (stopReadingsWatch) {
        stopReadingsWatch();
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
      setTarget,
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
