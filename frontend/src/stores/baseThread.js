// Base-thread snapshot store.
//
// Mirrors the LinuxCNC runtime split: the 10 Hz ``/ws/telemetry``
// stream is the "servo thread" (time-critical position / state /
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
//     need (``progress`` / ``sensors`` / ``tools``) and reactivity
//     is preserved via ``storeToRefs``.
//   * trivial to extend — adding a new slow stream is one new
//     top-level field on the backend response, one new ref here,
//     and one new consumer. No new endpoint, no new timer.
//
// The store exposes a manual ``refresh()`` action so a future
// "force update" button (or a settings PUT) can trigger an
// out-of-band poll without waiting for the next interval.
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
//   const { progress, sensors, tools } = storeToRefs(baseThread)
//
//   // out-of-band refresh (e.g. after a settings PUT)
//   await baseThread.refresh()
//
// Adding a new slow stream (e.g. ``fans``):
//
//   1. Add a top-level field to the backend
//      ``BaseThreadSnapshotResponse`` Pydantic model in
//      ``backend/routers/base_thread.py`` and populate it in
//      ``get_base_thread_snapshot()``.
//   2. ``npm run generate-api`` to regenerate the TypeScript client.
//   3. Add a ref to ``state`` here and a defensive write inside
//      ``refresh()`` (mirror the ``sensors`` / ``tools`` block).
//   4. Update consumers — no new timer, no new endpoint.
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

// 1 Hz is the documented contract — the temperature chart rolls
// a 30 s window at 1 s ticks, the progress bar advances at most
// one G-code line per tick, and the tools panel only needs
// human-perceptible refreshes. Faster polling does not buy
// anything useful on the dashboard and just saturates NML.
const POLL_INTERVAL_MS = 1_000;

const DEFAULT_PROGRESS = Object.freeze({
  current_line: 0,
  motion_line: 0,
  total_lines: 0,
  file: "",
  // Mirror backend's INTERP_IDLE so the widget can render the
  // "no program" branch even before the first response lands.
  interp_state: 1,
});

export const useBaseThreadStore = defineStore("baseThread", {
  state: () => ({
    /** @type {{ current_line: number, motion_line: number, total_lines: number, file: string, interp_state: number }} */
    progress: { ...DEFAULT_PROGRESS },
    /** @type {Record<string, { actual: number, target: number }>} */
    sensors: {},
    /** @type {Array<Record<string, any>>} */
    tools: [],
    /** @type {string|null} */
    timestamp: null,
    /** 'disconnected' | 'connecting' | 'connected' | 'error' */
    connectionStatus: "disconnected",
  }),
  getters: {
    /** Convenience getter for components that only need the bar fraction. */
    progressFraction(state) {
      const total = Number(state.progress.total_lines);
      const current = Number(state.progress.current_line);
      if (!Number.isFinite(total) || total <= 0) return 0;
      if (!Number.isFinite(current) || current < 0) return 0;
      return Math.min(100, (current / total) * 100);
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
          const p = snapshot.progress;
          this.progress = {
            current_line: Number(p.current_line) || 0,
            motion_line: Number(p.motion_line) || 0,
            total_lines: Number(p.total_lines) || 0,
            file: typeof p.file === "string" ? p.file : "",
            interp_state: Number(p.interp_state) || 1,
          };
        }

        if (snapshot.sensors && typeof snapshot.sensors === "object") {
          // Coerce each entry to a plain ``{actual, target}`` so
          // consumers can rely on the shape regardless of how the
          // backend serialised it.
          const next = {};
          for (const [name, reading] of Object.entries(snapshot.sensors)) {
            if (!reading || typeof reading !== "object") continue;
            next[name] = {
              actual: Number(reading.actual) || 0,
              target: Number(reading.target) || 0,
            };
          }
          this.sensors = next;
        }

        if (Array.isArray(snapshot.tools)) {
          // Shallow-clone each tool so the store never mutates the
          // upstream payload in place.
          this.tools = snapshot.tools.map((tool) => ({ ...tool }));
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
