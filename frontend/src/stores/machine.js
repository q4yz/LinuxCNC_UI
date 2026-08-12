// Machine store — cross-module runtime data.
//
// The Pinia store that backs every cross-module consumer of
// machine state. Lives in ``stores/`` (alongside ``stateFacade``,
// ``servoThread``, ``baseThread``) so any consumer can import from
// a single runtime-stores layer instead of reaching into
// ``modules/machine/``. The machine module's own components
// still import via the module's ``../store.js`` re-export — see
// ``frontend/src/modules/machine/store.js``.
//
// The nullable-module contract this store used to back has been
// dropped — the temperature module has never had it, and
// treating the machine module as a hard dependency simplifies
// the cross-module surface. Deleting ``stores/machineStoreShim.js``
// is the matching technical-debt cleanup. The store id
// ``"module_machine"`` is hardcoded here so ``stores/`` does
// not depend on ``modules/``; the
// ``frontend/scripts/check-store-ids.mjs`` lint still validates
// the regex, and the module's ``manifest.id === "machine"`` is
// the human source of truth for the constant.

import { defineStore, storeToRefs } from "pinia";
import { computed, reactive, ref } from "vue";

import { generateSetOffset } from "../config/gcodes.js";
import { ModulesMachineService } from "../../generated/api/services/ModulesMachineService";
import { ModulesProgramService } from "../../generated/api/services/ModulesProgramService";
import { useConsoleStore } from "./console.js";
import { useServoThreadStore } from "./servoThread.js";
import { createModuleSettings } from "../core/modules/settings.js";

// Axis index → letter mapping (matches ``gcodes.js`` conventions).
const AXIS_NAMES = ["X", "Y", "Z"];

// Sentinel accepted by the backend ``/home`` endpoint to home all axes.
const HOME_ALL = -1;
const DEFAULT_JOG_VELOCITY = 500;
const DEFAULT_KEEPALIVE_INTERVAL_MS = 250;

// Hardcoded — must equal ``modules/machine/manifest.js::id`` so
// the ``module_`` prefix rule (``.agent/STATE.md`` § 2) holds.
// The lint script ``frontend/scripts/check-store-ids.mjs`` catches
// drift between this constant and the manifest at CI time.
const MACHINE_MANIFEST_ID = "machine";
const STORE_ID = `module_${MACHINE_MANIFEST_ID}`;

const machineSettings = createModuleSettings(MACHINE_MANIFEST_ID);


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

  // The WebSocket transport is opened by ``modules/machine/index.js``
  // (``useServoThreadStore().start()``) and by ``App.vue``'s fallback
  // boot for the case where the module is absent. The store no
  // longer owns a ``start`` / ``stop`` surface — see
  // ``stores/servoThread.js`` for the lifecycle.

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
      // Prefer the open WebSocket — no extra HTTP round-trip per
      // jog start. The REST endpoint stays as a fallback in case
      // the socket is mid-reconnect.
      servo.send({
        type: "jog_axis",
        velocities: { [axis]: velocity },
        distance,
      });
      try {
        await ModulesMachineService.jogAxis({
          velocities: { [axis]: velocity },
          distance,
        });
      } catch (err) {
        // eslint-disable-next-line no-console
        console.error("Failed to jog axis (REST fallback)", axis, err);
      }
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
      // Start the jog over WS so the backend's watchdog
      // registers the axis on the very first frame. The REST
      // fallback covers the WS-reconnect case.
      servo.send({
        type: "jog_axis",
        velocities: { [axis]: jogVelocity },
        distance: 0,
      });
      try {
        await ModulesMachineService.jogAxis({
          velocities: { [axis]: jogVelocity },
          distance: 0,
        });
      } catch (err) {
        // eslint-disable-next-line no-console
        console.error("Failed to start continuous jog (REST fallback)", err);
      }

      // Keep-alive cadence comes from the persisted module
      // setting (250 ms fallback). The backend watchdog trips at
      // 500 ms. The ping goes over the open WebSocket — no HTTP
      // round-trip per axis per 250 ms (a continuous jog on X+Y+Z
      // previously generated 12 RTT/s).
      jogIntervals[axis] = setInterval(() => {
        servo.send({ type: "jog_keepalive", axes: [axis] });
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
      // Clear the keep-alive interval first so a slow WS message
      // doesn't fire after the stop has been issued.
      if (jogIntervals[axis]) {
        clearInterval(jogIntervals[axis]);
        delete jogIntervals[axis];
      }

      // Prefer the WebSocket — the stop takes effect on the next
      // 10 Hz broadcast tick. REST stays as a fallback in case
      // the socket is mid-reconnect.
      servo.send({ type: "jog_stop", axes: [axis] });
      try {
        await ModulesMachineService.jogStop({ axes: [axis] });
      } catch (err) {
        // eslint-disable-next-line no-console
        console.error("Failed to stop jog (REST fallback)", err);
      }
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
 * Convenience wrapper around ``storeToRefs`` so callers can
 * destructure the reactive state without losing reactivity.
 * Mirrors the same helper in every other runtime store
 * (``stateFacade.js``, ``servoThread.js``, ``baseThread.js``).
 *
 * @returns {{store: import('pinia').Store, ...import('vue').ToRefs<...>}}
 */
export function useMachineRefs() {
  const store = useMachineStore();
  return { store, ...storeToRefs(store) };
}

export default useMachineStore;