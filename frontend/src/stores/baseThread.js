// Base-thread snapshot store.
//
// Mirrors the LinuxCNC runtime split: the 10 Hz ``/ws/telemetry``// stream is the "servo thread" (time-critical position / state /
// errors), and this store is the "base thread" — a single 1 Hz
// REST round-trip that bundles every slow stream the dashboard
// cares about (program progress, temperature sensors, tool list)
// into one payload.
//
// Why one store instead of three independent ``setInterval`` timers:
//
//   * three polls → one poll. The browser issues one HTTP request
//     per second regardless of how many panels are mounted.
//   * single source of truth — consumers destructure the ref they
//     need (``progress`` / ``readings`` / ``tools``) and reactivity
//     is preserved via ``storeToRefs``.
//   * trivial to extend — adding a new slow stream is one new
//     top-level field on the backend response, one new ref here,
//     and one new consumer. No new endpoint, no new timer.
//
// ───────────────────────────────────────────────────────────────────
// USAGE
// ───────────────────────────────────────────────────────────────────
//
// Boot the store ONCE at app mount, then read from any consumer:
//
//   // frontend/src/App.vue (script setup, top level)
//   import { useBaseThreadStore } from './stores/baseThread'
//   useBaseThreadStore().start()       // idempotent — safe to call
//                                      // from hot-reload boundaries
//
//   // any consumer module
//   import { useBaseThreadStore } from '../../stores/baseThread.js'
//   const baseThread = useBaseThreadStore()
//   const { progress, readings, tools } = storeToRefs(baseThread)
//
//   // out-of-band refresh (e.g. after a settings PUT)
//   await baseThread.refresh()
//
// ───────────────────────────────────────────────────────────────────
// STATE LAYERS
// ───────────────────────────────────────────────────────────────────
//
// The store exposes both the **raw wire shape** (legacy ``sensors``
// dict, ``tools`` array) and the **typed entity surface**
// (``readings: ReadingSet``, ``toolList: ToolList``, ``progress``).
// Migrating consumers to the entity surface is the goal of the
// anti-corruption layer (see ``frontend/src/entities`` and
// ``frontend/src/facades``); the legacy surface stays until every
// consumer has moved.
//
// ───────────────────────────────────────────────────────────────────
// GOTCHAS (see ``.agent/context/LESSONS_LEARNED.md`` § 2.5)
// ───────────────────────────────────────────────────────────────────
//
// * ``_pollHandle`` is a non-state property on the Pinia store
//   instance — it starts as ``undefined``. The ``start`` / ``stop``
//   gates must use a truthy check (``if (this._pollHandle)``), not
//   a strict-null check (``if (this._pollHandle !== null)``), or
//   the first ``start()`` call returns early and the 1 Hz poll
//   never begins.
// * Consumers in sibling modules must watch with ``deep: true`` and
//   pull the current value synchronously at setup time. Pinia
//   OPTIONS-API's top-level reassignment does not always
//   rebroadcast across module boundaries via the proxy.
// * The WebSocket telemetry (servo thread) deliberately does NOT
//   carry temperature sensors, tool list, or program progress —
//   those moved to this base-thread snapshot. Do not add them back
//   to ``/ws/telemetry``.

import { defineStore } from "pinia";

import { BaseThreadService } from "../../generated/api/index.ts";
import { ReadingSet } from "../entities/temperature/ReadingSet.js";
import { ToolList } from "../entities/tools/ToolList.js";
import { ProgramProgress } from "../entities/progress/ProgramProgress.js";
import { HeaterReading, SensorReading } from "../entities/temperature/Reading.js";
import { SpindleState, ExtruderState } from "../entities/tools/index.js";
import {
  toReading,
  toReadingSet,
} from "../mappers/temperatureMapper.js";
import { toProgramProgress } from "../mappers/progressMapper.js";
import {
  toToolList,
  toSpindleState,
  toExtruderState,
  toHeaterReading,
} from "../mappers/toolsMapper.js";

// 1 Hz is the documented contract — the temperature chart rolls
// a 30 s window at 1 s ticks, the progress bar advances at most
// one G-code line per tick, and the tools panel only needs
// human-perceptible refreshes. Faster polling does not buy
// anything useful on the dashboard and just saturates NML.
const POLL_INTERVAL_MS = 1_000;

const DEFAULT_PROGRESS = Object.freeze({
  currentLine: 0,
  motionLine: 0,
  totalLines: 0,
  file: "",
  interpState: 1,
});

const EMPTY_READINGS = new ReadingSet([]);
const EMPTY_TOOLS = new ToolList([]);

export const useBaseThreadStore = defineStore("baseThread", {
  state: () => ({
    /** @type {ProgramProgress} */
    progress: new ProgramProgress({ ...DEFAULT_PROGRESS }),

    /**
     * Legacy wire shape — preserved during the migration window
     * so existing consumers keep working. Keys are tool_ids
     * (``HeaterStateResponse.tool_id`` / ``TemperatureStateResponse.tool_id``).
     * @type {Record<string, object>}
     */
    sensors: {},

    /**
     * Typed entity surface — replaces the legacy ``sensors`` dict
     * once consumers migrate.
     * @type {ReadingSet}
     */
    readings: EMPTY_READINGS,

    /**
     * Legacy wire shape — preserved during the migration window.
     * @type {Array<Record<string, any>>}
     */
    tools: [],

    /**
     * Typed entity surface — replaces ``tools`` once consumers migrate.
     * @type {ToolList}
     */
    toolList: EMPTY_TOOLS,

    /** @type {string|null} */
    timestamp: null,

    /** 'disconnected' | 'connecting' | 'connected' | 'error' */
    connectionStatus: "disconnected",
  }),
  getters: {
    /** Convenience getter for components that only need the bar fraction. */
    progressFraction(state) {
      const fraction = state.progress.fraction;
      return Number.isFinite(fraction) ? fraction : 0;
    },
  },
  actions: {
    /**
     * Pull the latest snapshot from the backend and write every
     * field into the store. Best-effort: a failed tick leaves the
     * previous values intact so the operator keeps seeing the last
     * known state. The ``connectionStatus`` flips to ``"error"``
     * on a failure and back to ``"connected"`` on the next success.
     */
    async refresh() {
      try {
        const snapshot = await BaseThreadService.getBaseThreadSnapshot();
        if (!snapshot || typeof snapshot !== "object") {
          // eslint-disable-next-line no-console
          console.warn("[baseThread] snapshot empty or non-object", snapshot);
          return;
        }

        // Progress: only overwrite when the backend sent a valid
        // object so a half-built snapshot cannot blank the bar.
        if (snapshot.progress && typeof snapshot.progress === "object") {
          this.progress = toProgramProgress(snapshot.progress);
        }

        if (snapshot.sensors && typeof snapshot.sensors === "object") {
          // ── Legacy shape (kept for the migration window) ──
          // Coerce each entry to a plain ``{actual, target}`` so
          // the few remaining raw-shape consumers can rely on the
          // keys regardless of which backend response model
          // produced the row.
          const next = {};
          for (const [name, reading] of Object.entries(snapshot.sensors)) {
            if (!reading || typeof reading !== "object") continue;
            const hasHeaterFields =
              reading.target !== undefined && reading.target !== null;
            next[name] = {
              tool_id:
                typeof reading.tool_id === "string" ? reading.tool_id : name,
              actual: Number(reading.actual) || 0,
              ...(hasHeaterFields && {
                target: Number(reading.target) || 0,
                min_temp: Number(reading.min_temp) || 0,
                max_temp: Number(reading.max_temp) || 0,
              }),
            };
          }
          this.sensors = next;

          // ── Typed entity surface ──
          // The discriminator (target present vs absent) lives
          // entirely in the mapper; entity consumers never branch
          // on it.
          this.readings = toReadingSet(snapshot.sensors);
        }

        if (Array.isArray(snapshot.tools)) {
          // ── Legacy shape (shallow-cloned) ──
          this.tools = snapshot.tools.map((tool) => ({ ...tool }));

          // ── Typed entity surface ──
          this.toolList = toToolList(snapshot.tools);
        }

        this.timestamp =
          typeof snapshot.timestamp === "string" ? snapshot.timestamp : null;
        this.connectionStatus = "connected";
      } catch (err) {
        // Loud logging — silent swallows have masked two
        // regressions already (see commit history). Operators can
        // still ignore the console but a regression is now obvious.
        // eslint-disable-next-line no-console
        console.error("[baseThread] refresh failed:", err);
        this.connectionStatus = "error";
      }
    },

    /**
     * Start the 1 Hz polling loop. Idempotent: re-entering while
     * a loop is already running is a no-op so hot-reloads and
     * double-mounts do not stack intervals.
     */
    start() {
      // Truthy check (not strict null) — the handle is a non-state
      // property on the store instance, so it is ``undefined`` on
      // the first call. A strict-null check (``!== null``) would
      // see ``undefined !== null`` as ``true`` and return early,
      // which silently disables the 1 Hz poll.
      if (this._pollHandle) return;
      this.connectionStatus = "connecting";
      // Fire immediately so the operator sees populated data on
      // the first frame after mount, then settle into the 1 Hz
      // cadence.
      void this.refresh();
      this._pollHandle = setInterval(() => {
        void this.refresh();
      }, POLL_INTERVAL_MS);
    },

    /**
     * Stop the polling loop. Safe to call when the loop is not
     * running; safe to call twice. Exposed for tests and for the
     * future ``onScopeDispose`` hook on the store's host module.
     */
    stop() {
      // Same truthy check as ``start`` — keeps the two actions
      // symmetric and tolerates either ``undefined`` or ``null``.
      if (!this._pollHandle) return;
      clearInterval(this._pollHandle);
      this._pollHandle = null;
      this.connectionStatus = "disconnected";
    },
  },
});

export default useBaseThreadStore;

// Re-export the entity factories so consumers that build synthetic
// readings (tests, dev tooling) don't have to reach into the
// entity module directly.
export {
  HeaterReading,
  SensorReading,
  ReadingSet,
  SpindleState,
  ExtruderState,
  ToolList,
  ProgramProgress,
};
