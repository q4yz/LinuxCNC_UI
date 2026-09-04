// Machine store — cross-module runtime data.
import {defineStore, storeToRefs} from "pinia";
import {computed, ref} from "vue";

import {generateSetOffset} from "../config/gcodes";
import {useConsoleStore} from "./console";
import {useServoThreadStore} from "./servoThread";
import {createModuleSettings} from "../core/settings/createModuleSettings";
import {servoThreadService} from "../facades/servoThreadFacade";
import {axisFacade} from "../facades/axisFacade";
import {machineStateFacade} from "../facades/machineStateFacade";
import {progressFacade} from "../facades/progressFacade";
import {CommandResult} from "../entities/common/CommandResult";
import {reportCommandFailure, describeError} from "../core/error-format";

// Axis index → letter mapping (matches ``gcodes.js`` conventions).
const AXIS_NAMES = ["X", "Y", "Z", "A", "B", "C", "U", "V", "W"];

// Sentinel accepted by the backend ``/home`` endpoint to home all axes.
const HOME_ALL: "all" = "all";
const DEFAULT_JOG_VELOCITY = 500;
const DEFAULT_KEEPALIVE_INTERVAL_MS = 250;

// The backend has no ``machine`` module — the per-axis machine
// settings (``default_jog_velocity``, ``keepalive_interval_ms``,
// ``jog_watchdog_timeout_ms``, ``estop_disables_power``) actually
// live under the ``axis`` module. This mirrors the mount in
// ``backend/main.py`` (``_MODULE_DOMAINS``) and the historical
// note in ``MachineSettingsPanel.vue:18-26``: every other frontend
// surface that touches these settings already passes ``"axis"``.
// Earlier this constant was ``"machine"`` which produced a boot-time
// 404 at ``/api/v1/modules/machine/settings`` and silently fell back
// to the hard-coded defaults above.
const MACHINE_ID = "axis";
const STORE_ID = MACHINE_ID;

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

const machineSettings = createModuleSettings(MACHINE_ID);

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

    const defaultJogVelocity = ref(DEFAULT_JOG_VELOCITY);
    const keepaliveIntervalMs = ref(DEFAULT_KEEPALIVE_INTERVAL_MS);
    const isUpdating = ref(false);

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

    let settingsLoaded = false;
    let settingsLoadPromise: Promise<void> | null = null;

    async function refreshSettings(): Promise<void> {
        // Idempotent: a second caller while the first load is in
        // flight awaits the same promise so we never fire two
        // HTTP round-trips for the same store instance.
        if (settingsLoaded) return;
        if (settingsLoadPromise) return settingsLoadPromise;
        settingsLoadPromise = (async () => {
            try {
                const settings = await machineSettings.readAll();
                if (settings && typeof settings === "object") {
                    const velocity = Number(settings.default_jog_velocity);
                    if (Number.isFinite(velocity) && velocity >= 1) {
                        defaultJogVelocity.value = velocity;
                    }

                    const interval = Number(settings.keepalive_interval_ms);
                    if (Number.isFinite(interval) && interval >= 50 && interval <= 2000) {
                        keepaliveIntervalMs.value = interval;
                    }
                }
            } catch (err) {
                console.warn("Machine settings unavailable; using defaults", err);
            } finally {
                settingsLoaded = true;
            }
        })();
        return settingsLoadPromise;
    }

    // Eagerly kick off the settings load when the store is first
    // instantiated so the first jog click does not have to await a
    // round-trip before sending ``jog_axis``. Previously the await
    // lived inside ``jogContinuous``, which created a race: a quick
    // click-and-release let ``stopJog`` finish before
    // ``jogContinuous`` ever reached the WebSocket, leaving a
    // keep-alive interval running for a jog the operator already
    // cancelled. Loading eagerly (fire-and-forget) closes that
    // window — the values land before any operator input on every
    // realistic boot.
    void refreshSettings();

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
            // Settings are loaded eagerly on store creation; do not
            // await here — the discrete jog would race against a
            // subsequent ``stopJog`` if it ever had to wait on the
            // HTTP round-trip. Fall back to the documented defaults
            // (``DEFAULT_JOG_VELOCITY``) if the load is still in
            // flight on the very first click.
            const velocity = Number.isFinite(defaultJogVelocity.value)
                ? defaultJogVelocity.value
                : DEFAULT_JOG_VELOCITY;

            consoleStore.info(`Jogging ${axisName} axis ${distance}mm`);

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
        // No await on ``refreshSettings`` here — see ``jog`` above.
        // The keep-alive interval is set up synchronously inside
        // ``servoThreadService.jogContinuous`` so a click-and-release
        // that lands before the settings round-trip resolves still
        // produces a paired ``jog_axis`` + ``jog_stop`` over the
        // socket; awaiting would let the operator's ``stopJog``
        // overtake the jog and leave the axis running on a zombie
        // keep-alive timer.
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
        keepaliveIntervalMs,
        isUpdating,
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
        refreshSettings,
        toggleEstop,
        activateEstop,
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
