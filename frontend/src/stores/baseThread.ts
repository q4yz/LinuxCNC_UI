// Base-thread snapshot store.
//
// Mirrors the LinuxCNC runtime split: the 10 Hz `/ws/telemetry`
// stream is the "servo thread" (time-critical position / state /
// errors), and this store is the "base thread" — a single 1 Hz
// REST round-trip that bundles every slow stream the dashboard
// cares about.

import { defineStore } from "pinia";
import { ref, shallowRef, computed } from "vue";

import { BaseThreadService } from "../../facades/BaseThreadService";

// Entity imports for state typing and re-exporting
import { ReadingSet } from "../entities/temperature/ReadingSet";
import { ToolList } from "../entities/tools/ToolList";
import { ProgramProgress } from "../entities/progress/ProgramProgress";
import { HeaterReading, SensorReading } from "../entities/temperature/Reading";
import { SpindleState } from "../entities/tools/SpindleState";
import { Extruder } from "../entities/tools/Extruder";

// 1 Hz is the documented contract.
const POLL_INTERVAL_MS = 1_000;

export const useBaseThreadStore = defineStore("baseThread", () => {
  // ─────────────────────────────────────────────────────────────────
  // STATE
  // ─────────────────────────────────────────────────────────────────

  // Typed entity surface (shallowRef is massive for performance here,
  // as it prevents deep proxying of class instances every 1 Hz)
  const progress = shallowRef<ProgramProgress>(new ProgramProgress());
  const readings = shallowRef<ReadingSet>(new ReadingSet());
  const toolList = shallowRef<ToolList>(new ToolList([]));

  // Legacy wire shape (kept for migration window)
  const sensors = ref<Record<string, any>>({});
  const tools = ref<Record<string, any>[]>([]);

  const timestamp = ref<string | null>(null);

  type ConnectionStatus = "disconnected" | "connecting" | "connected" | "error";
  const connectionStatus = ref<ConnectionStatus>("disconnected");

  // Non-reactive internals. This fixes the old gotcha: since it's a local
  // variable and not in a `state: () => ({})` block, Vue won't wrap it in a proxy.
  let pollHandle: ReturnType<typeof setInterval> | null = null;

  // ─────────────────────────────────────────────────────────────────
  // GETTERS
  // ─────────────────────────────────────────────────────────────────

  /** Convenience getter for components that only need the bar fraction. */
  const progressFraction = computed(() => {
    const fraction = progress.value.fraction;
    return Number.isFinite(fraction) ? fraction : 0;
  });

  // ─────────────────────────────────────────────────────────────────
  // ACTIONS
  // ─────────────────────────────────────────────────────────────────

  /**
   * Pull the latest snapshot from the backend and write every
   * field into the store. Best-effort: a failed tick leaves the
   * previous values intact so the operator keeps seeing the last
   * known state.
   */
  async function refresh() {
    try {
      // The BaseThreadService handles all data extraction and mappers now
      const snapshot = await BaseThreadService.fetchSnapshot();

      // Entity Surface
      progress.value = snapshot.progress;
      readings.value = snapshot.readings;
      toolList.value = snapshot.toolList;

      timestamp.value = snapshot.timestamp;
      connectionStatus.value = "connected";
    } catch (err: unknown) {
      // Loud logging — silent swallows have masked two regressions already.
      console.error("[baseThread] refresh failed:", err);
      connectionStatus.value = "error";
    }
  }

  /**
   * Start the 1 Hz polling loop. Idempotent: re-entering while
   * a loop is already running is a no-op so hot-reloads and
   * double-mounts do not stack intervals.
   */
  function start() {
    if (pollHandle) return;

    connectionStatus.value = "connecting";

    // Fire immediately so the operator sees populated data on
    // the first frame after mount, then settle into the 1 Hz cadence.
    void refresh();

    pollHandle = setInterval(() => {
      void refresh();
    }, POLL_INTERVAL_MS);
  }

  /**
   * Stop the polling loop. Safe to call when the loop is not
   * running; safe to call twice. Exposed for tests and for the
   * future `onScopeDispose` hook on the store's host module.
   */
  function stop() {
    if (!pollHandle) return;

    clearInterval(pollHandle);
    pollHandle = null;
    connectionStatus.value = "disconnected";
  }

  // ─────────────────────────────────────────────────────────────────
  // PUBLIC API
  // ─────────────────────────────────────────────────────────────────
  return {
    // State
    progress,
    readings,
    toolList,
    sensors,
    tools,
    timestamp,
    connectionStatus,
    // Getters
    progressFraction,
    // Actions
    refresh,
    start,
    stop,
  };
});

export default useBaseThreadStore;

export {
  HeaterReading,
  SensorReading,
  ReadingSet,
  SpindleState as SpindleDigital, // Exported as SpindleDigital to not break legacy imports
  Extruder,
  ToolList,
  ProgramProgress,
};