// Machine store — cross-module runtime data.
import {defineStore, storeToRefs} from "pinia";
import {computed, ref} from "vue";

import {generateSetOffset} from "../config/gcodes";
import {ModulesAxisService} from "../../generated/api";
import {ModulesMachineStateService} from "../../generated/api";
import {ModulesProgramService} from "../../generated/api";
import {useConsoleStore} from "./console";
import {useServoThreadStore} from "./servoThread";
import {createModuleSettings} from "../core/modules/settings";
import {servoThreadService} from "../facades/servoThreadFacade";

// Axis index → letter mapping (matches ``gcodes.js`` conventions).
const AXIS_NAMES = ["X", "Y", "Z", "A", "B", "C", "U", "V", "W"];

// Sentinel accepted by the backend ``/home`` endpoint to home all axes.
const HOME_ALL = -1;
const DEFAULT_JOG_VELOCITY = 500;
const DEFAULT_KEEPALIVE_INTERVAL_MS = 250;

const MACHINE_MANIFEST_ID = "machine";
const STORE_ID = `module_${MACHINE_MANIFEST_ID}`;

const machineSettings = createModuleSettings(MACHINE_MANIFEST_ID);

export const useMachineStore = defineStore(STORE_ID, () => {
    // ──────────────────────────────────────────────────────────────── //
    // Composed state                                                     //
    // ──────────────────────────────────────────────────────────────── //

    const servo = useServoThreadStore();
    // ``status`` is a computed over the reactive Proxy returned by
    // Pinia for ``servo.status`` (a ``Ref<ServoThreadState>``). The
    // facade MUST mutate it via ``servo.setFullState`` /
    // ``servo.applyDelta`` so Vue's ``set`` trap fires and re-runs
    // every computed below. Bypassing the store (e.g.
    // ``servo.status.patch(...)``) drops the update silently.
    const status = computed(() => servo.status);
    const connectionStatus = computed(() => servo.connectionStatus);
    //const errors = computed(() => servo.errors || []);
    //const isUpdating = computed(() => servo.isUpdating || false);

    // ──────────────────────────────────────────────────────────────── //
    // Module-private state                                               //
    // ──────────────────────────────────────────────────────────────── //

    const defaultJogVelocity = ref(DEFAULT_JOG_VELOCITY);
    const keepaliveIntervalMs = ref(DEFAULT_KEEPALIVE_INTERVAL_MS);

    // ──────────────────────────────────────────────────────────────── //
    // Derived values (Using the new ServoThreadState getters!)           //
    // ──────────────────────────────────────────────────────────────── //

    const droX = computed(() => (status.value.relativePosition?.[0] || 0).toFixed(3));
    const droY = computed(() => (status.value.relativePosition?.[1] || 0).toFixed(3));
    const droZ = computed(() => (status.value.relativePosition?.[2] || 0).toFixed(3));

    const isEstop = computed(() => status.value.isEstop);
    const isMachineOn = computed(() => status.value.isMachineOn);
    const isPrinting = computed(() => status.value.isPrinting);
    const isPaused = computed(() => status.value.isPaused);
    const printProgress = computed(() => status.value.printProgress);

    const machineStateText = computed(() => {
        if (status.value.isEstop) return "ESTOP";
        if (status.value.taskState === 3) return "OFF";
        if (status.value.taskState === 4) return "ON";
        return "READY";
    });

    const isLoaded = computed(() =>
        status.value.taskState === 4 &&
        status.value.interpState === 1 &&
        typeof status.value.file === "string" &&
        status.value.file.length > 0
    );

    // ──────────────────────────────────────────────────────────────── //
    // Lifecycle                                                          //
    // ──────────────────────────────────────────────────────────────── //

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
            if (Number.isFinite(interval) && interval >= 50 && interval <= 2000) {
                keepaliveIntervalMs.value = interval;
            }
            settingsLoaded = true;
        } catch (err) {
            settingsLoaded = true;
            console.warn("Machine settings unavailable; using defaults", err);
        }
    }

    // ──────────────────────────────────────────────────────────────── //
    // Hardware actions                                                   //
    // ──────────────────────────────────────────────────────────────── //

    async function toggleEstop() {
        const consoleStore = useConsoleStore();
        const targetState = status.value.isEstop ? "estop_reset" : "estop";
        try {
            await ModulesMachineStateService.setMachineState({state: targetState});
            if (targetState === "estop") {
                consoleStore.warning("E-STOP Engaged");
            } else {
                consoleStore.success("E-STOP Cleared");
            }
        } catch (err) {
            consoleStore.error(`Failed to toggle ESTOP: ${err.message}`);
            console.error("Failed to toggle ESTOP", err);
        }
    }

    async function togglePower() {
        const consoleStore = useConsoleStore();
        const isOn = status.value.isMachineOn;
        const estop = status.value.isEstop;

        if (estop && !isOn) {
            consoleStore.warning("Cannot turn on machine while ESTOP is active");
            return;
        }

        const targetState = isOn ? "off" : "on";
        try {
            await ModulesMachineStateService.setMachineState({state: targetState});
            if (targetState === "on") {
                consoleStore.success("Machine Power ON");
            } else {
                consoleStore.success("Machine Power OFF");
            }
        } catch (err) {
            consoleStore.error(`Failed to toggle Power: ${err.message}`);
            console.error("Failed to toggle Power", err);
        }
    }

    // --- Jogging Methods (Delegated to Service) ---

    async function jog(axis: number, distance: number) {
        const consoleStore = useConsoleStore();
        const axisName = AXIS_NAMES[axis];
        try {
            if (!settingsLoaded) await refreshSettings();
            const velocity = Number.isFinite(defaultJogVelocity.value)
                ? defaultJogVelocity.value
                : DEFAULT_JOG_VELOCITY;

            consoleStore.info(`Jogging ${axisName} axis ${distance}mm`);

            // Dispatch discrete jog through the service
            servoThreadService.send({type: "jog_axis", velocities: {[axis]: velocity}, distance,});
        } catch (err) {
            consoleStore.error(`Failed to jog ${axisName}: ${err.message}`);
            console.error("Failed to jog axis", axis, err);
        }
    }

    async function jogContinuous(axis: number, velocity: number) {
        if (!settingsLoaded) await refreshSettings();
        const requestedVelocity = Number(velocity);
        const jogVelocity = Number.isFinite(requestedVelocity)
            ? requestedVelocity
            : defaultJogVelocity.value;
        const intervalMs = Number.isFinite(keepaliveIntervalMs.value)
            ? keepaliveIntervalMs.value
            : DEFAULT_KEEPALIVE_INTERVAL_MS;

        // The service handles all the `setInterval` and logging logic!
        servoThreadService.jogContinuous(axis, jogVelocity, intervalMs);
    }

    async function jogStop(axis: number) {
        // The service handles the `clearInterval` and logging logic!
        servoThreadService.jogStop(axis);
    }

    // ──────────────────────────────────────────────────────────────── //
    // Homing + coordinate system                                         //
    // ──────────────────────────────────────────────────────────────── //

    async function homeAxis(axisIndex: number) {
        const consoleStore = useConsoleStore();
        try {
            consoleStore.info(`Homing axis index ${axisIndex}...`);
            await ModulesAxisService.homeAxis({axis: axisIndex});
            consoleStore.success(`Homed axis ${axisIndex} successfully`);
        } catch (err) {
            consoleStore.error(`Failed to home axis ${axisIndex}: ${err.message}`);
            console.error("Failed to home axis", axisIndex, err);
        }
    }

    async function homeAll() {
        const consoleStore = useConsoleStore();
        try {
            consoleStore.info("Homing all axes...");
            await ModulesAxisService.homeAxis({axis: HOME_ALL});
            consoleStore.success("All axes homed successfully");
        } catch (err) {
            consoleStore.error(`Failed to home all axes: ${err.message}`);
            console.error("Failed to home all axes", err);
        }
    }

    async function setPosition(axisIndex: number, value: number) {
        const consoleStore = useConsoleStore();
        const axisName = AXIS_NAMES[axisIndex];
        if (!axisName) return;
        try {
            consoleStore.command(`Setting work offset for ${axisName} to ${value}...`);
            const cmd = generateSetOffset(axisName, value);
            await ModulesMachineStateService.runMdiCommand({command: cmd});
        } catch (err) {
            consoleStore.error(`Failed to set position for ${axisName}: ${err.message}`);
            console.error("Failed to set position for axis", axisIndex, err);
        }
    }

    async function setCoordinateSystem(gcodeString: string) {
        const consoleStore = useConsoleStore();
        try {
            consoleStore.command(`Switching to Coordinate System: ${gcodeString}`);
            await ModulesMachineStateService.runMdiCommand({command: gcodeString});
        } catch (err) {
            consoleStore.error(`Failed to switch Coordinate System: ${err.message}`);
            console.error("Failed to switch coordinate system", err);
        }
    }

    // ──────────────────────────────────────────────────────────────── //
    // Program lifecycle actions                                          //
    // ──────────────────────────────────────────────────────────────── //

    async function startProgram(filename: string) {
        if (!filename || typeof filename !== "string") return;
        const consoleStore = useConsoleStore();
        try {
            consoleStore.command(`Loading program ${filename}...`);
            await ModulesProgramService.loadProgram({filename});
            consoleStore.success(`Loaded ${filename} — press Start to begin.`);
        } catch (err) {
            consoleStore.error(`Failed to load ${filename}: ${err.body?.detail || err.message}`);
            console.error("Failed to load program", filename, err);
        }
    }

    async function loadProgram(filename: string) {
        if (!filename || typeof filename !== "string") return;
        const consoleStore = useConsoleStore();
        try {
            await ModulesProgramService.loadProgram({filename});
        } catch (err) {
            consoleStore.error(`Failed to load ${filename}: ${err.body?.detail || err.message}`);
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
            console.error("Failed to abort program", err);
        }
    }

    // ──────────────────────────────────────────────────────────────── //
    // Public surface                                                    //
    // ──────────────────────────────────────────────────────────────── //

    return {
        connectionStatus,
        status,
        defaultJogVelocity,
        keepaliveIntervalMs,
        //isUpdating,
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
        refreshSettings,
        toggleEstop,
        togglePower,
        jog,
        jogContinuous,
        jogStop,
        homeAxis,
        homeAll,
        setPosition,
        setCoordinateSystem,
        startProgram,
        loadProgram,
        pauseProgram,
        resumeProgram,
        abortProgram,
    };
});

export function useMachineRefs() {
    const store = useMachineStore();
    return {store, ...storeToRefs(store)};
}

export default useMachineStore;