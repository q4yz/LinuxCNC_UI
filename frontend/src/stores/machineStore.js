// State Facade store. Exposes raw LinuxCNC integers
// (``task_state``, ``interp_state``, ``estop``) plus a clean
// string-based ``systemState`` getter so the frontend never does
// integer math against the wire protocol. ``updateStatus`` is the
// single sanctioned entry point for telemetry — called by the
// machine module's WebSocket handler on every ``full_state`` /
// ``delta`` update. See ``.agent/STATE.md`` § 6.

import { defineStore } from "pinia";

// Raw LinuxCNC integer constants. Mirrors
// ``hardware/linuxcnc_mock.py``. Frozen so a component cannot
// silently desynchronise from the backend.
export const TASK_STATE = Object.freeze({
  ESTOP: 1,
  ESTOP_RESET: 2,
  OFF: 3,
  ON: 4,
});

export const INTERP_STATE = Object.freeze({
  IDLE: 1,
  READING: 2,
  PAUSED: 3,
  WAITING: 4,
});

// Frontend state enum the UI uses instead of raw integers.
// ``Object.freeze`` keeps the table immutable at runtime.
export const SystemState = Object.freeze({
  OFFLINE: "Offline",
  UPDATING: "Updating",
  ESTOP: "Estop",
  POWER_OFF: "PowerOff",
  IDLE: "Idle",
  RUNNING: "Running",
  PAUSED: "Paused",
  FAILURE: "Failure",
});

// Safe default payload for the initial render before the first
// telemetry frame arrives. ``ESTOP`` is the safest default: the UI
// must never claim the machine is idle or running when we have no
// data.
const DEFAULT_RAW_STATUS = Object.freeze({
  task_state: TASK_STATE.ESTOP,
  estop: 1,
  task_mode: 1,
  interp_state: INTERP_STATE.IDLE,
  file: "",
  current_line: 0,
  total_lines: 0,
});

// Sanity-check the constants at module load. A future refactor that
// renames or reorders them would silently disagree with the
// backend — this guard fails fast instead.
(function validateConstants() {
  const taskValues = Object.values(TASK_STATE);
  const expectedTask = [1, 2, 3, 4];
  if (
    taskValues.length !== expectedTask.length ||
    !expectedTask.every((v) => taskValues.includes(v))
  ) {
    // eslint-disable-next-line no-console
    console.warn(
      "[machineStore] TASK_STATE values drifted from the backend contract",
      TASK_STATE,
    );
  }
  const interpValues = Object.values(INTERP_STATE);
  const expectedInterp = [1, 2, 3, 4];
  if (
    interpValues.length !== expectedInterp.length ||
    !expectedInterp.every((v) => interpValues.includes(v))
  ) {
    // eslint-disable-next-line no-console
    console.warn(
      "[machineStore] INTERP_STATE values drifted from the backend contract",
      INTERP_STATE,
    );
  }
})();

// ---------------------------------------------------------------------- //
// Pinia store                                                            //
// ---------------------------------------------------------------------- //

export const useMachineStore = defineStore("machineStore", {
  state: () => ({
    // 'disconnected' | 'connecting' | 'connected' — mirrors the
    // machine module's WebSocket lifecycle so the facade can short-
    // circuit to ``Offline`` when no telemetry is flowing.
    connectionStatus: "disconnected",
    // Whether the backend is in the middle of a configuration update
    // (``status: "updating"``). The widget hides progress during an
    // update so the operator does not panic over a frozen bar.
    isUpdating: false,
    // Raw telemetry payload. ``systemState`` is for state-based UI;
    // advanced / diagnostic panels can read the integers here.
    status: { ...DEFAULT_RAW_STATUS },
  }),

  getters: {
    /**
     * String-based machine state facade. Components that only need
     * "what is the machine doing right now?" should always go
     * through this getter. Priority (highest wins):
     * Offline → Updating → Estop → PowerOff → Paused → Running
     * → Idle → Failure.
     */
    systemState(state) {
      if (state.connectionStatus !== "connected") return SystemState.OFFLINE;
      if (state.isUpdating) return SystemState.UPDATING;

      const raw = state.status;

      if (raw.task_state === TASK_STATE.ESTOP || raw.estop === 1) {
        return SystemState.ESTOP;
      }

      if (
        raw.task_state === TASK_STATE.ESTOP_RESET ||
        raw.task_state === TASK_STATE.OFF
      ) {
        return SystemState.POWER_OFF;
      }

      if (raw.task_state === TASK_STATE.ON) {
        if (raw.interp_state === INTERP_STATE.PAUSED) {
          return SystemState.PAUSED;
        }
        if (
          raw.interp_state === INTERP_STATE.READING ||
          raw.interp_state === INTERP_STATE.WAITING
        ) {
          return SystemState.RUNNING;
        }
        return SystemState.IDLE;
      }

      return SystemState.FAILURE;
    },

    /**
     * Print progress as a 0–100 percentage. Returns 0 when the
     * backend has not reported ``total_lines`` for the current
     * program, when ``total_lines`` is 0, or when ``current_line``
     * is negative (a stale frame). The value is clamped at 100 so a
     * "near end" run cannot display >100%.
     */
    printProgress(state) {
      const total = Number(state.status.total_lines);
      const current = Number(state.status.current_line);
      if (!Number.isFinite(total) || total <= 0) return 0;
      if (!Number.isFinite(current) || current < 0) return 0;
      return Math.min(100, (current / total) * 100);
    },

    /**
     * Explicit boolean for safety-critical UI blocks. Kept as a
     * separate getter so a guard clause can short-circuit without
     * a string compare against ``SystemState.ESTOP``.
     */
    isEstopActive(state) {
      return (
        state.status.estop === 1 ||
        state.status.task_state === TASK_STATE.ESTOP
      );
    },

    /**
     * Mocked recent-files list — the real implementation will read
     * from ``NcFilesService.listFiles`` (or a future
     * ``recentFiles`` endpoint) once it lands. Shape matches
     * ``FileInfo`` so ``ActivePrintWidget`` does not have to change.
     */
    recentFiles() {
      return [
        { filename: "demo_box.gcode", modified: "2026-07-25T10:00:00Z", size_bytes: 24576 },
        { filename: "spiral_v2.ngc",   modified: "2026-07-24T15:30:00Z", size_bytes: 16384 },
        { filename: "calibration.ngc", modified: "2026-07-23T09:15:00Z", size_bytes: 8192  },
        { filename: "hex_grid.gcode",  modified: "2026-07-22T18:45:00Z", size_bytes: 32768 },
        { filename: "first_run.gcode", modified: "2026-07-21T12:05:00Z", size_bytes: 4096  },
      ];
    },
  },

  actions: {
    /**
     * Receive a fresh payload from the transport layer. The shape
     * mirrors what the backend's WebSocket stream emits; this action
     * is the only sanctioned way to mutate the raw state so the
     * facade never goes out of sync with the module store.
     *
     * @param {{ connectionStatus?: string, isUpdating?: boolean, status?: object }} newPayload
     */
    updateStatus(newPayload) {
      if (!newPayload || typeof newPayload !== "object") return;
      if (typeof newPayload.connectionStatus === "string") {
        this.connectionStatus = newPayload.connectionStatus;
      }
      if (typeof newPayload.isUpdating === "boolean") {
        this.isUpdating = newPayload.isUpdating;
      }
      if (newPayload.status && typeof newPayload.status === "object") {
        // Replace rather than merge so a stale key does not linger
        // between full-state updates.
        this.status = { ...DEFAULT_RAW_STATUS, ...newPayload.status };
      }
    },
  },
});

export default useMachineStore;