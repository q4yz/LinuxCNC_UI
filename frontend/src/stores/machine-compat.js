// Optional compatibility adapter for consumers that predate the machine
// module.  The real implementation registers itself here when the module is
// mounted; when the module is absent (or disabled), the fallback store keeps
// the rest of the shell renderable without importing a deleted module path.

import { defineStore, storeToRefs } from "pinia";
import { computed, reactive, ref } from "vue";

const fallbackStatus = {
  task_state: 1,
  estop: 1,
  task_mode: 1,
  position: [0, 0, 0, 0, 0, 0, 0, 0, 0],
  actual_position: [0, 0, 0, 0, 0, 0, 0, 0, 0],
  relative_position: [0, 0, 0, 0, 0, 0, 0, 0, 0],
  state: 1,
  file: "",
  homed: [0, 0, 0],
  interp_state: 1,
  current_line: 0,
  total_lines: 0,
  g5x_index: 1,
};

const useFallbackMachineStore = defineStore("module_machine_fallback", () => {
  const connectionStatus = ref("disconnected");
  const status = reactive({ ...fallbackStatus });
  const errors = ref([]);
  const jogIntervals = reactive({});
  const isUpdating = ref(false);

  const droX = computed(() => (status.relative_position[0] || 0).toFixed(3));
  const droY = computed(() => (status.relative_position[1] || 0).toFixed(3));
  const droZ = computed(() => (status.relative_position[2] || 0).toFixed(3));
  const isEstop = computed(() => status.estop === 1);
  const isMachineOn = computed(() => status.task_state === 4);
  const machineStateText = computed(() => {
    if (status.estop === 1) return "ESTOP";
    if (status.task_state === 3) return "OFF";
    if (status.task_state === 4) return "ON";
    return "READY";
  });
  // Mirror the program-run derived values exposed by the module store so
  // widgets render consistently when the optional machine module is not
  // mounted.
  const isPrinting = computed(
    () => status.task_state === 2 && status.interp_state !== 3,
  );
  const isPaused = computed(
    () => status.task_state === 2 && status.interp_state === 3,
  );
  // Mirrors the SystemState.LOADED branch of the primary store
  // facade: machine is ON, interpreter is idle, but a file is
  // selected. Used by the dashboard widget to render the new
  // "Loaded" branch with a dedicated Start button.
  const isLoaded = computed(
    () =>
      status.task_state === 4 &&
      status.interp_state === 1 &&
      typeof status.file === "string" &&
      status.file.length > 0,
  );
  const printProgress = computed(() => {
    const total = Number(status.total_lines);
    const current = Number(status.current_line);
    if (!Number.isFinite(total) || total <= 0) return 0;
    if (!Number.isFinite(current) || current < 0) return 0;
    return Math.min(100, (current / total) * 100);
  });

  const noop = async () => undefined;
  const disconnect = () => {
    connectionStatus.value = "disconnected";
    for (const axis of Object.keys(jogIntervals)) {
      clearInterval(jogIntervals[axis]);
      delete jogIntervals[axis];
    }
  };

  return {
    connectionStatus,
    status,
    errors,
    jogIntervals,
    defaultJogVelocity: ref(500),
    keepaliveIntervalMs: ref(250),
    isUpdating,
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
    connect: noop,
    disconnect,
    refreshSettings: noop,
    toggleEstop: noop,
    togglePower: noop,
    jog: noop,
    jogContinuous: noop,
    jogStop: noop,
    homeAxis: noop,
    homeAll: noop,
    setPosition: noop,
    setCoordinateSystem: noop,
    setTargetTemperature: noop,
    startProgram: noop,
    loadProgram: noop,
    pauseProgram: noop,
    resumeProgram: noop,
    abortProgram: noop,
  };
});

let registeredMachineStore = null;

/** Register the module-owned Pinia store for legacy consumers. */
export function registerMachineStore(useStore) {
  registeredMachineStore = useStore;
}

/** Clear the registration during module shutdown / hot reload. */
export function unregisterMachineStore(useStore) {
  if (registeredMachineStore === useStore) {
    registeredMachineStore = null;
  }
}

/**
 * Compatibility entry point used by pre-migration components.  It deliberately
 * does not statically import the optional machine module, so deleting that
 * module leaves a buildable, inert application.
 */
export function useMachineStore(...args) {
  const useStore = registeredMachineStore || useFallbackMachineStore;
  return useStore(...args);
}

export function useMachineRefs() {
  const store = useMachineStore();
  return { store, ...storeToRefs(store) };
}

export default useMachineStore;
