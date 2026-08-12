// Machine module Pinia store.
//
// Owns the machine-module-specific actions (jog, home, set
// position, set coordinate system, set target temperature, program
// lifecycle) and the per-axis keep-alive timers. The high-
// frequency telemetry now lives in ``stores/servoThread.js`` —
// this store composes that store for the live ``status`` /
// ``connectionStatus`` / ``errors`` fields so widgets that bind
// against the legacy ``useMachineStore()`` shim (see
// ``stores/machineStoreShim.js``) keep working unchanged.
//
// The runtime split:
//
//   * Servo thread — 10 Hz ``/ws/telemetry`` WebSocket stream.
//     Transport + reactive state live in ``stores/servoThread.js``.
//
//   * Base thread — 1 Hz ``/api/v1/base-thread/snapshot`` REST
//     round-trip (program progress, temperature sensors, tool
//     list). See ``stores/baseThread.js``.
//
// This store registers itself with the legacy compat shim so
// pre-migration components that call ``useMachineStore()`` (via
// ``stores/machineStoreShim.js``) get a coherent view. The shim
// resolves to this store when the machine module is mounted; when
// it isn't, the shim's fallback store keeps the shell renderable.

import { defineStore, storeToRefs } from "pinia";
import { computed, reactive, ref } from "vue";

import manifest from "./manifest.js";
import { generateSetOffset } from "../../config/gcodes.js";
import { ModulesMachineService } from "../../../generated/api/services/ModulesMachineService";
import { ModulesProgramService } from "../../../generated/api/services/ModulesProgramService";
import { useConsoleStore } from "../../stores/console.js";
import { useServoThreadStore } from "../../stores/servoThread.js";
import {
  registerMachineStore,
  unregisterMachineStore,
} from "../../stores/machineStoreShim.js";
import { createModuleSettings } from "../../core/modules/settings.js";

// Axis index → letter mapping (matches ``gcodes.js`` conventions).
const AXIS_NAMES = ["X", "Y", "Z"];

// Sentinel accepted by the backend ``/home`` endpoint to home all axes.
const HOME_ALL = -1;
const DEFAULT_JOG_VELOCITY = 500;
const DEFAULT_KEEPALIVE_INTERVAL_MS = 250;

const machineSettings = createModuleSettings(manifest.id);

// ``module_`` prefix prevents collisions with legacy top-level
// stores. See ``.agent/STATE.md`` § 2.
const STORE_ID = `module_${manifest.id}`;


export const useMachineStore = defineStore(STORE_ID, () => {
  // ──────────────────────────────────────────────────────────────── //
  // Composed state                                                     //
  // ──────────────────────────────────────────────────────────────── //

  // Telemetry state comes from the servo-thread store (10 Hz
  // ``/ws/telemetry`` WebSocket). The machine module is no longer
  // the owner of the socket or the ``status`` payload — see
  // ``stores/servoThread.js`` for the transport.
  const servo = useServoThreadStore();
  const { status, connectionStatus, errors, isUpdating } =
    storeToRefs(servo);

  // ──────────────────────────────────────────────────────────────── //
  // Module-private state                                               //
  // ──────────────────────────────────────────────────────────────── //

  // Per-axis keep-alive handles for continuous jogging. Cleared
  // on ``stopContinuousJog`` / on module teardown.
  const jogIntervals = reactive({});

  // Persisted settings. ``refreshSettings()`` populates these
  // from the backend; the machine module owns the read because
  // they're module-scoped.
  const defaultJogVelocity = ref(DEFAULT_JOG_VELOCITY);
  const keepaliveIntervalMs = ref(DEFAULT_KEEPALIVE_INTERVAL_MS);

  // ──────────────────────────────────────────────────────────────── //
  // Derived values                                                     //
  // ──────────────────────────────────────────────────────────────── //

  const droX = computed(
    () => (status.value.relative_position?.[0] || 0).toFixed(3),
  );
  const droY = computed(
    () => (status.value.relative_position?.[1] || 0).toFixed(3),
  );
  const droZ = computed(
    () => (status.value.relative_position?.[2] || 0).toFixed(3),
  );

  const isEstop = computed(() => status.value.estop === 1);
  const isMachineOn = computed(() => status.value.task_state === 4);

  const machineStateText = computed(() => {
    if (status.value.estop === 1) return "ESTOP";
    if (status.value.task_state === 3) return "OFF";
    if (status.value.task_state === 4) return "ON";
    return "READY";
  });

  // ``isPrinting`` and ``isPaused`` are mutually exclusive: a paused
  // program is *not* reported as printing so the widget can swap
  // its "Pause" button for "Resume" without flickering.
  const isPrinting = computed(
    () => status.value.task_state === 2 && status.value.interp_state !== 3,
  );
  const isPaused = computed(
    () => status.value.task_state === 2 && status.value.interp_state === 3,
  );

  // Mirrors the SystemState.LOADED branch of the State Facade:
  // machine is ON, interpreter is idle, but a file is selected.
  // Used by the dashboard widget to render the "Loaded" branch
  // with a dedicated Start button.
  const isLoaded = computed(
    () =>
      status.value.task_state === 4 &&
      status.value.interp_state === 1 &&
      typeof status.value.file === "string" &&
      status.value.file.length > 0,
  );

  const printProgress = computed(() => {
    const total = Number(status.value.total_lines);
    const current = Number(status.value.current_line);
    if (!Number.isFinite(total) || total <= 0) return 0;
    if (!Number.isFinite(current) || current < 0) return 0;
    return Math.min(100, (current / total) * 100);
  });

  // ──────────────────────────────────────────────────────────────── //
  // Lifecycle                                                          //
  // ──────────────────────────────────────────────────────────────── //

  // Re-exported from the servo-thread store. The machine module's
  // ``start`` / ``stop`` surface used to open and close the socket
  // directly — that responsibility moved to ``useServoThreadStore``
  // and the boot is wired from ``App.vue`` so the transport
  // outlives any single module.

  let settingsLoaded = false;

  async function refreshSettings() {
    try {
      const settings = await machineSettings.readAll();
      if (!settings || typeof settings !== "object") {
        settingsLoaded = true;
        return;
      }

      const velocity = Number(settings.default_jog_velocity);
      if (Number.isFinite(velocity) && velocity >= 1) {
        defaultJogVelocity.value = velocity;
      }

      const interval = Number(settings.keepalive_interval_ms);
      if (
        Number.isFinite(interval) &&
        interval >= 50 &&
        interval <= 2000
      ) {
        keepaliveIntervalMs.value = interval;
      }
      settingsLoaded = true;
    } catch (err) {
      // Settings are optional while the machine module is
      // disabled or during the first frontend render. Keep safe
      // historical defaults.
      settingsLoaded = true;
      // eslint-disable-next-line no-console
      console.warn("Machine settings unavailable; using defaults", err);
    }
  }

  // ──────────────────────────────────────────────────────────────── //
  // Hardware actions                                                   //
  // ──────────────────────────────────────────────────────────────── //

  async function toggleEstop() {
    const consoleStore = useConsoleStore();
    // ``estop == 1`` means we need to reset; otherwise we engage.
    const targetState = status.value.estop === 1 ? "estop_reset" : "estop";
    try {
      await ModulesMachineService.setMachineState({ state: targetState });
      if (targetState === "estop") {
        consoleStore.warning("E-STOP Engaged");
      } else {
        consoleStore.success("E-STOP Cleared");
      }
    } catch (err) {
      consoleStore.error(
        `Failed to toggle ESTOP: ${err.message}`,
      );
      // eslint-disable-next-line no-console
      console.error("Failed to toggle ESTOP", err);
    }
  }

  async function togglePower() {
    const consoleStore = useConsoleStore();
    // ``task_state`` 4 == ON, 3 == OFF.
    const isOn = status.value.task_state === 4;
    const estop = status.value.estop === 1;
    if (estop && !isOn) {
      consoleStore.warning(
        "Cannot turn on machine while ESTOP is active",
      );
      return;
    }
    const targetState = isOn ? "off" : "on";
    try {
      await ModulesMachineService.setMachineState({ state: targetState });
      if (targetState === "on") {
        consoleStore.success("Machine Power ON");
      } else {
        consoleStore.success("Machine Power OFF");
      }
    } catch (err) {
      consoleStore.error(
        `Failed to toggle Power: ${err.message}`,
      );
      // eslint-disable-next-line no-console
      console.error("Failed to toggle Power", err);
    }
  }

  async function jog(axis, distance) {
    const consoleStore = useConsoleStore();
    const axisName = AXIS_NAMES[axis];
    try {
      if (!settingsLoaded) await refreshSettings();
      const velocity = Number.isFinite(defaultJogVelocity.value)
        ? defaultJogVelocity.value
        : DEFAULT_JOG_VELOCITY;
      consoleStore.info(
        `Jogging ${axisName} axis ${distance}mm`,
      );
      await ModulesMachineService.jogAxis({
        velocities: { [axis]: velocity },
        distance,
      });
    } catch (err) {
      consoleStore.error(
        `Failed to jog ${axisName}: ${err.message}`,
      );
      // eslint-disable-next-line no-console
      console.error("Failed to jog axis", axis, err);
    }
  }

  async function jogContinuous(axis, velocity) {
    const consoleStore = useConsoleStore();
    const axisName = AXIS_NAMES[axis];
    try {
      // Load persisted defaults if the module was mounted before
      // its settings request completed.
      if (!settingsLoaded) await refreshSettings();

      const requestedVelocity = Number(velocity);
      const jogVelocity = Number.isFinite(requestedVelocity)
        ? requestedVelocity
        : defaultJogVelocity.value;
      const intervalMs = Number.isFinite(keepaliveIntervalMs.value)
        ? keepaliveIntervalMs.value
        : DEFAULT_KEEPALIVE_INTERVAL_MS;

      // Clear any existing interval to prevent ghost loops.
      if (jogIntervals[axis]) {
        clearInterval(jogIntervals[axis]);
        delete jogIntervals[axis];
      }

      consoleStore.info(
        `Jogging ${axisName} axis continuously...`,
      );
      await ModulesMachineService.jogAxis({
        velocities: { [axis]: jogVelocity },
        distance: 0,
      });

      // Keep-alive cadence comes from the persisted module
      // setting (250 ms fallback). The backend watchdog trips at
      // 500 ms.
      jogIntervals[axis] = setInterval(async () => {
        try {
          await ModulesMachineService.jogKeepalive({ axes: [axis] });
        } catch (err) {
          // eslint-disable-next-line no-console
          console.error(
            `Keepalive ping failed for axis ${axis}:`,
            err,
          );
        }
      }, intervalMs);
    } catch (err) {
      consoleStore.error(
        `Failed to start continuous jog: ${err.message}`,
      );
      // eslint-disable-next-line no-console
      console.error("Failed to start continuous jog", err);
    }
  }

  async function jogStop(axis) {
    const consoleStore = useConsoleStore();
    const axisName = AXIS_NAMES[axis];
    try {
      if (jogIntervals[axis]) {
        clearInterval(jogIntervals[axis]);
        delete jogIntervals[axis];
      }

      await ModulesMachineService.jogStop({ axes: [axis] });
      consoleStore.info(`${axisName} Jog stopped`);
    } catch (err) {
      consoleStore.error(
        `Failed to stop jog: ${err.message}`,
      );
      // eslint-disable-next-line no-console
      console.error("Failed to stop jog", err);
    }
  }

  // ──────────────────────────────────────────────────────────────── //
  // Homing + coordinate system                                         //
  // ──────────────────────────────────────────────────────────────── //

  async function homeAxis(axisIndex) {
    const consoleStore = useConsoleStore();
    try {
      consoleStore.info(`Homing axis index ${axisIndex}...`);
      await ModulesMachineService.homeAxis({ axis: axisIndex });
      consoleStore.success(
        `Homed axis ${axisIndex} successfully`,
      );
    } catch (err) {
      consoleStore.error(
        `Failed to home axis ${axisIndex}: ${err.message}`,
      );
      // eslint-disable-next-line no-console
      console.error("Failed to home axis", axisIndex, err);
    }
  }

  async function homeAll() {
    const consoleStore = useConsoleStore();
    try {
      consoleStore.info("Homing all axes...");
      await ModulesMachineService.homeAxis({ axis: HOME_ALL });
      consoleStore.success("All axes homed successfully");
    } catch (err) {
      consoleStore.error(
        `Failed to home all axes: ${err.message}`,
      );
      // eslint-disable-next-line no-console
      console.error("Failed to home all axes", err);
    }
  }

  async function setPosition(axisIndex, value) {
    const consoleStore = useConsoleStore();
    const axisName = AXIS_NAMES[axisIndex];
    if (!axisName) return;
    try {
      consoleStore.command(
        `Setting work offset for ${axisName} to ${value}...`,
      );
      const cmd = generateSetOffset(axisName, value);
      await ModulesMachineService.runMdiCommand({ command: cmd });
    } catch (err) {
      consoleStore.error(
        `Failed to set position for ${axisName}: ${err.message}`,
      );
      // eslint-disable-next-line no-console
      console.error("Failed to set position for axis", axisIndex, err);
    }
  }

  async function setCoordinateSystem(gcodeString) {
    const consoleStore = useConsoleStore();
    try {
      consoleStore.command(
        `Switching to Coordinate System: ${gcodeString}`,
      );
      await ModulesMachineService.runMdiCommand({ command: gcodeString });
    } catch (err) {
      consoleStore.error(
        `Failed to switch Coordinate System: ${err.message}`,
      );
      // eslint-disable-next-line no-console
      console.error("Failed to switch coordinate system", err);
    }
  }

  // ──────────────────────────────────────────────────────────────── //
  // Program lifecycle actions                                          //
  // ──────────────────────────────────────────────────────────────── //
  //
  // Each action only dispatches the request — the backend's
  // telemetry stream mirrors the new state on the next tick so
  // widgets do not need to maintain local flags.

  async function startProgram(filename) {
    if (!filename || typeof filename !== "string") return;
    const consoleStore = useConsoleStore();
    try {
      // Step 1 of the two-step lifecycle: load the program into
      // the interpreter. The backend (program/router.py)
      // validates the filename against the upload root, calls
      // ``command.program_open``, and returns 200 on success. The
      // widget's reactive state transitions to SystemState.LOADED
      // on the next telemetry tick and the operator presses Start
      // to invoke ``runProgram``.
      consoleStore.command(`Loading program ${filename}...`);
      await ModulesProgramService.loadProgram({ filename });
      consoleStore.success(`Loaded ${filename} — press Start to begin.`);
    } catch (err) {
      consoleStore.error(
        `Failed to load ${filename}: ${err.body?.detail || err.message}`,
      );
      // eslint-disable-next-line no-console
      console.error("Failed to load program", filename, err);
    }
  }

  async function loadProgram(filename) {
    if (!filename || typeof filename !== "string") return;
    const consoleStore = useConsoleStore();
    try {
      await ModulesProgramService.loadProgram({ filename });
    } catch (err) {
      consoleStore.error(
        `Failed to load ${filename}: ${err.body?.detail || err.message}`,
      );
      // eslint-disable-next-line no-console
      console.error("Failed to load program", filename, err);
    }
  }

  async function pauseProgram() {
    const consoleStore = useConsoleStore();
    try {
      consoleStore.info("Pausing program");
      await ModulesProgramService.pauseProgram();
    } catch (err) {
      consoleStore.error(`Failed to pause program: ${err.message}`);
      // eslint-disable-next-line no-console
      console.error("Failed to pause program", err);
    }
  }

  async function resumeProgram() {
    const consoleStore = useConsoleStore();
    try {
      consoleStore.info("Resuming program");
      await ModulesProgramService.resumeProgram();
    } catch (err) {
      consoleStore.error(`Failed to resume program: ${err.message}`);
      // eslint-disable-next-line no-console
      console.error("Failed to resume program", err);
    }
  }

  async function abortProgram() {
    const consoleStore = useConsoleStore();
    try {
      consoleStore.warning("Aborting program");
      await ModulesProgramService.stopProgram();
    } catch (err) {
      consoleStore.error(`Failed to abort program: ${err.message}`);
      // eslint-disable-next-line no-console
      console.error("Failed to abort program", err);
    }
  }

  // ──────────────────────────────────────────────────────────────── //
  // Compatibility shim                                                 //
  // ──────────────────────────────────────────────────────────────── //
  //
  // ``stores/machineStoreShim.js`` resolves ``useMachineStore()``
  // to whichever store was registered last. The machine module
  // registers itself on mount and unregisters on teardown so the
  // shim falls back to its inert fallback when the module is
  // disabled.

  // Register this store on mount via the immediate callback so
  // hot-reloads don't end up with a stale registration pointing
  // at a torn-down instance.
  registerMachineStore(useMachineStore);

  // ──────────────────────────────────────────────────────────────── //
  // Public surface                                                    //
  // ──────────────────────────────────────────────────────────────── //

  return {
    // Reactive state (composed from the servo-thread store).
    connectionStatus,
    status,
    errors,
    jogIntervals,
    defaultJogVelocity,
    keepaliveIntervalMs,
    isUpdating,
    // Derived values (formally getters).
    droX,
    droY,
    droZ,
    isEstop,
    isMachineOn,
    machineStateText,
    isPrinting,
    isPaused,
    isLoaded,
    printProgress,
    // Settings.
    refreshSettings,
    // Hardware actions.
    toggleEstop,
    togglePower,
    jog,
    jogContinuous,
    jogStop,
    homeAxis,
    homeAll,
    setPosition,
    setCoordinateSystem,
    // Program lifecycle actions.
    startProgram,
    loadProgram,
    pauseProgram,
    resumeProgram,
    abortProgram,
  };
});

/**
 * Helper that wraps :func:`storeToRefs` so callers can destructure
 * the reactive state without losing reactivity. Re-exported here so
 * module consumers have a single import surface.
 *
 * @returns {{store: import('pinia').Store, ...import('vue').ToRefs<...>}}
 */
export function useMachineRefs() {
  const store = useMachineStore();
  return { store, ...storeToRefs(store) };
}

/**
 * Called from ``modules/machine/index.js`` when the module is
 * torn down. Clears the registration so the shim falls back to
 * its inert fallback on the next mount.
 */
export function unregister() {
  unregisterMachineStore(useMachineStore);
}

export default useMachineStore;