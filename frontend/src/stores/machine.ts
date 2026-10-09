// Machine store — cross-module runtime data.
import {defineStore, storeToRefs} from "pinia";
import {computed, ref} from "vue";

import {generateSetOffset} from "../config/gcodes";
import {useConsoleStore} from "./console";
import {useServoThreadStore} from "./servoThread";
import {defaultJogVelocity as defaultJogVelocitySetting} from "../settings/definitions/machine";
import {servoThreadService} from "../facades/servoThreadFacade";
import {axisFacade} from "../facades/axisFacade";
import {machineStateFacade} from "../facades/machineStateFacade";
import {mcuFacade} from "../facades/mcuFacade";
import {progressFacade} from "../facades/progressFacade";
import {CommandResult} from "../entities/common/CommandResult";
import {reportCommandFailure, describeError} from "../core/error-format";

// Axis index → letter mapping (matches ``gcodes.js`` conventions).
const AXIS_NAMES = ["X", "Y", "Z", "A", "B", "C", "U", "V", "W"];

// Sentinel accepted by the backend ``/home`` endpoint to home all axes.
const HOME_ALL: "all" = "all";
// Jog keep-alive cadence. Not a user setting: it must stay well below
// the backend's jog watchdog timeout (``jog_watchdog.WATCHDOG_TIMEOUT_S``,
// 500 ms) or a held jog key stops the axis.
const KEEPALIVE_INTERVAL_MS = 250;

const STORE_ID = "axis";

/**
 * Canonical LinuxCNC axis letter identifiers. Used by the homing
 * payload (wire contract) so the operator-facing strings travel
 * end-to-end without an index↔letter translation layer. The
 * string values match the canonical ``hardware.json`` axis ids
 * (``id: "x"`` / ``id: "y"`` / ``id: "z"``) and the
 * ``AxisState.id`` field on the base-thread snapshot.
 *
 * Erasable ``as const`` object (not a TS ``enum``) so the runtime
 * strip-types loader can load this module.
 */
export const Axis = {
  X: "x",
  Y: "y",
  Z: "z",
} as const;
export type Axis = (typeof Axis)[keyof typeof Axis];

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

    // ──────────────────────────────────────────────────────────────── //
    // Module-private state                                               //
    // ──────────────────────────────────────────────────────────────── //

    // Central UI setting (``machine.default_jog_velocity``): its default
    // until the stored value arrives — a UI preference, so that's fine.
    const defaultJogVelocity = computed(() => defaultJogVelocitySetting.value ?? defaultJogVelocitySetting.defaultValue);

    // ──────────────────────────────────────────────────────────────── //
    // Derived values (Using the new ServoThreadState getters!)           //
    // ──────────────────────────────────────────────────────────────── //

    const droX = computed(() => (status.value.relativePosition?.[0] || 0).toFixed(3));
    const droY = computed(() => (status.value.relativePosition?.[1] || 0).toFixed(3));
    const droZ = computed(() => (status.value.relativePosition?.[2] || 0).toFixed(3));

    const isEstop = computed(() => status.value.isEstop);
    const isEstopActive = computed(() => status.value.isEstop);
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


    // ──────────────────────────────────────────────────────────────── //
    // Hardware actions                                                   //
    //                                                                         //
    // Every manual-trigger action returns ``Promise<CommandResult>`` so     //
    // the Vue component layer always sees the same uniform shape. The       //
    // failure path is channelled through ``reportCommandFailure`` so the    //
    // console row + toast are byte-identical across every action.           //
    // ──────────────────────────────────────────────────────────────── //

    async function toggleEstop(): Promise<CommandResult> {
        const consoleStore = useConsoleStore();
        const targetState = status.value.isEstop ? "estop_reset" : "estop";
        const result = await machineStateFacade.setState(targetState);
        if (result.failed) {
            reportCommandFailure("toggle ESTOP", result);
        } else if (targetState === "estop") {
            consoleStore.warning("E-STOP Engaged");
        } else {
            consoleStore.success("E-STOP Cleared");
        }
        return result;
    }

    /**
     * Critical e-stop activation. Always-engage — no state check, no
     * toggle. Drives ``halui.estop.activate`` directly via HAL so the
     * servo thread reacts within one period (~1 ms) instead of the
     * multi-stage NML round-trip that ``toggleEstop`` takes.
     *
     * The button that calls this action (``EStopHeader.vue``) stays
     * pressable at all times, including when the UI is out of sync
     * with the machine (e.g., a hardware reset cleared ESTOP but the
     * WebSocket telemetry hasn't caught up yet). Idempotent: pressing
     * while already engaged is a no-op semantically.
     */
    async function activateEstop(): Promise<CommandResult> {
        const consoleStore = useConsoleStore();
        const result = await machineStateFacade.activateEstop();
        if (result.failed) {
            reportCommandFailure("activate ESTOP", result);
        } else {
            consoleStore.warning("E-STOP Engaged");
        }
        return result;
    }

    /**
     * Reset every resettable MCU (Remora boards that declared a
     * ``reset_pin``). The backend pulses each board's
     * ``webgui.<id>-reset`` HAL pin; the button is only shown when
     * ``baseThread.hasResettableMcu`` is true.
     */
    async function resetMcus(): Promise<CommandResult> {
        const consoleStore = useConsoleStore();
        const result = await mcuFacade.resetMcus();
        if (result.failed) {
            reportCommandFailure("reset MCU", result);
        } else {
            consoleStore.success(`MCU reset sent: ${result.message || "all"}`, {popup: true});
        }
        return result;
    }

    async function togglePower(): Promise<CommandResult> {
        const consoleStore = useConsoleStore();
        const isOn = status.value.isMachineOn;
        const estop = status.value.isEstop;

        if (estop && !isOn) {
            consoleStore.warning("Cannot turn on machine while ESTOP is active");
            return CommandResult.failure("ESTOP active");
        }

        const targetState = isOn ? "off" : "on";
        const result = await machineStateFacade.setState(targetState);
        if (result.failed) {
            reportCommandFailure("toggle power", result);
        } else if (targetState === "on") {
            consoleStore.success("Machine Power ON");
        } else {
            consoleStore.success("Machine Power OFF");
        }
        return result;
    }

    // --- Jogging Methods (kept on the WebSocket path) ---
    //
    // Per the design decision documented in the plan, continuous
    // jogging over the telemetry WebSocket is fire-and-forget, not a
    // request/response, so it does not go through ``CommandResult``.
    // A simple ``consoleStore`` row is sufficient and a toast would
    // be operator-noise on every keep-alive tick.

    async function jog(axis: number, distance: number) {
        const consoleStore = useConsoleStore();
        const axisName = AXIS_NAMES[axis];
        try {
            // Never awaits a settings fetch — the setting serves its
            // default until the stored value has arrived.
            const velocity = defaultJogVelocity.value;

            consoleStore.debug(`Jogging ${axisName} axis ${distance}mm`);

            // Dispatch discrete jog through the service
            servoThreadService.send({
                type: "jog_axis",
                velocities: {[axis]: velocity},
                distance,
            });
        } catch (err: unknown) {
            consoleStore.error(`Failed to jog ${axisName}: ${describeError(err)}`);
            console.error("Failed to jog axis", axis, err);
        }
    }

    async function jogContinuous(axis: number, velocity: number) {
        // Nothing is awaited here: the keep-alive interval is set up
        // synchronously inside ``servoThreadService.jogContinuous`` so a
        // quick click-and-release still produces a paired ``jog_axis`` +
        // ``jog_stop`` — awaiting would let ``stopJog`` overtake the jog
        // and leave the axis running on a zombie keep-alive timer.
        const requestedVelocity = Number(velocity);
        const jogVelocity = Number.isFinite(requestedVelocity)
            ? requestedVelocity
            : defaultJogVelocity.value;
        // The service handles all the `setInterval` and logging logic!
        servoThreadService.jogContinuous(axis, jogVelocity, KEEPALIVE_INTERVAL_MS);
    }

    async function jogStop(axis: number) {
        // The service handles the `clearInterval` and logging logic!
        servoThreadService.jogStop(axis);
    }

    // ──────────────────────────────────────────────────────────────── //
    // Homing + coordinate system                                         //
    // ──────────────────────────────────────────────────────────────── //

    async function homeAxis(axis: Axis | "all"): Promise<CommandResult> {
        const result = await machineStateFacade.setHomeAxis(axis);
        if (result.failed) {
            reportCommandFailure(`home axis ${axis}`, result);
        } else {
            useConsoleStore().success(`Homed axis ${axis} successfully`);
        }
        return result;
    }

    async function homeAll(): Promise<CommandResult> {
        const result = await machineStateFacade.setHomeAxis(HOME_ALL);
        if (result.failed) {
            reportCommandFailure("home all axes", result);
        } else {
            useConsoleStore().success("All axes homed successfully");
        }
        return result;
    }

    async function setPosition(axisIndex: number, value: number): Promise<CommandResult> {
        const consoleStore = useConsoleStore();
        const axisName = AXIS_NAMES[axisIndex];
        if (!axisName) {
            return CommandResult.failure("Unknown axis index");
        }
        consoleStore.command(`Setting work offset for ${axisName} to ${value}...`);
        const cmd = generateSetOffset(axisName, value);
        const result = await machineStateFacade.sendMdi(cmd);
        if (result.failed) {
            reportCommandFailure(`set position for ${axisName}`, result);
        }
        return result;
    }

    async function setCoordinateSystem(gcodeString: string): Promise<CommandResult> {
        const consoleStore = useConsoleStore();
        consoleStore.command(`Switching to Coordinate System: ${gcodeString}`);
        const result = await machineStateFacade.sendMdi(gcodeString);
        if (result.failed) {
            reportCommandFailure("switch coordinate system", result);
        }
        return result;
    }

    async function updateAxisSettings(
        multiplier: number,
        absoluteSpeedLimit: number,
    ): Promise<CommandResult> {
        const consoleStore = useConsoleStore();
        const result = await axisFacade.updateSettings(multiplier, absoluteSpeedLimit);
        if (result.ok) {
            consoleStore.success(
                `Axis settings updated (${Math.round(multiplier * 100)}%, ${absoluteSpeedLimit} mm/min)`,
            );
        } else {
            reportCommandFailure("update axis settings", result);
        }
        return result;
    }

    // ──────────────────────────────────────────────────────────────── //
    // Program lifecycle actions                                          //
    // ──────────────────────────────────────────────────────────────── //

    async function startProgram(filename: string): Promise<CommandResult> {
        if (!filename || typeof filename !== "string") {
            return CommandResult.failure("Filename is required");
        }
        const consoleStore = useConsoleStore();
        const result = await progressFacade.loadProgram(filename);
        if (result.failed) {
            reportCommandFailure(`load ${filename}`, result);
        } else {
            consoleStore.success(`Loaded ${filename} — press Start to begin.`);
        }
        return result;
    }

    async function loadProgram(filename: string): Promise<CommandResult> {
        if (!filename || typeof filename !== "string") {
            return CommandResult.failure("Filename is required");
        }
        const result = await progressFacade.loadProgram(filename);
        if (result.failed) {
            reportCommandFailure(`load ${filename}`, result);
        }
        return result;
    }

    async function pauseProgram(): Promise<CommandResult> {
        const consoleStore = useConsoleStore();
        const result = await progressFacade.pauseProgram();
        if (result.failed) {
            reportCommandFailure("pause program", result);
        } else {
            consoleStore.info("Pausing program");
        }
        return result;
    }

    async function resumeProgram(): Promise<CommandResult> {
        const consoleStore = useConsoleStore();
        const result = await progressFacade.resumeProgram();
        if (result.failed) {
            reportCommandFailure("resume program", result);
        } else {
            consoleStore.info("Resuming program");
        }
        return result;
    }

    async function pauseInspect(): Promise<CommandResult> {
        const consoleStore = useConsoleStore();
        const result = await progressFacade.pauseInspect();
        if (result.failed) {
            reportCommandFailure("pause & inspect", result);
        } else {
            consoleStore.info("Pause & Inspect: tool lifted, spindle inhibited");
        }
        return result;
    }

    async function abortProgram(): Promise<CommandResult> {
        const consoleStore = useConsoleStore();
        const result = await progressFacade.stopProgram();
        if (result.failed) {
            reportCommandFailure("abort program", result);
        } else {
            consoleStore.warning("Aborting program");
        }
        return result;
    }

    async function unloadProgram(): Promise<CommandResult> {
        const result = await progressFacade.unloadProgram();
        if (result.failed) {
            reportCommandFailure("unload program", result);
        }
        return result;
    }

    async function runProgram(): Promise<CommandResult> {
        const result = await progressFacade.runProgram();
        if (result.failed) {
            reportCommandFailure("start program", result);
        }
        return result;
    }

    // ──────────────────────────────────────────────────────────────── //
    // Public surface                                                    //
    // ──────────────────────────────────────────────────────────────── //

    return {
        connectionStatus,
        status,
        defaultJogVelocity,
        droX,
        droY,
        droZ,
        isEstop,
        isEstopActive,
        isMachineOn,
        machineStateText,
        isPrinting,
        isPaused,
        isLoaded,
        printProgress,
        toggleEstop,
        activateEstop,
        resetMcus,
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
        runProgram,
        pauseProgram,
        resumeProgram,
        pauseInspect,
        abortProgram,
        unloadProgram,
        updateAxisSettings,
    };
});

export function useMachineRefs() {
    const store = useMachineStore();
    return {store, ...storeToRefs(store)};
}

export default useMachineStore;
