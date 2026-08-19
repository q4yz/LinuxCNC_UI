// stores/servoThread.ts
import {defineStore} from 'pinia';
import {ref} from 'vue';
import {ServoThreadState} from "../entities/servoThread/Telemetry";
import {ServoThreadStateResponse} from "../../generated/api";
import {useMachineStore as useFacadeStore} from "./stateFacade";


export const useServoThreadStore = defineStore('servoThread', () => {
    // ``status`` is a ``ref<ServoThreadState>``; Vue wraps the inner
    // class instance in a reactive ``Proxy`` on access. The facade
    // MUST go through ``setFullState`` / ``applyDelta`` so every
    // mutation flows through that Proxy and re-evaluates the
    // dependent computeds in ``stores/machine.ts`` (the ``isEstop``
    // / ``droX`` / ``machineStateText`` chain the UI binds to).
    // Reaching into ``store.status`` directly is fragile and was the
    // root cause of the E-Stop toggle not propagating to the UI.
    const status = ref<ServoThreadState>(new ServoThreadState());
    const connectionStatus = ref('disconnected');

    /**
     * Mirror the live state into the State Facade
     * (``stores/stateFacade.ts``). The facade is the consumer
     * surface for widgets that read the high-resolution vocabulary
     * (``systemState``, ``printProgress``, ``isEstopActive``) and
     * was the canonical entry point documented on
     * ``stateFacade.updateStatus``. The migration moved transport
     * out of the store but forgot to keep the bridge — the facade
     * was frozen on ``DEFAULT_RAW_STATUS`` until this mirror was
     * restored. The facade expects the raw snake_case payload,
     * so we flatten the class instance before dispatching.
     */
    const mirrorToFacade = (): void => {
        const facade = useFacadeStore();
        if (!facade || typeof facade.updateStatus !== "function") return;
        const s = status.value;
        facade.updateStatus({
            connectionStatus: connectionStatus.value,
            status: {
                task_state: s.taskState,
                estop: s.estop,
                task_mode: s.taskMode,
                interp_state: s.interpState,
                state: s.state,
                file: s.file,
                current_line: s.currentLine,
                total_lines: s.totalLines,
            },
        });
    };

    /**
     * Replace the current state with a freshly-constructed entity.
     * Used for the ``full_state`` envelope the backend emits on
     * every new WebSocket connection.
     */
    const setFullState = (newState: ServoThreadState) => {
        status.value = newState;
        mirrorToFacade();
    };

    /**
     * Apply an incoming ``delta`` frame (snake_case, partial) to
     * the current state. Routes through ``ServoThreadState.patch``
     * which only touches fields that are present + non-null, so a
     * single-field diff does not blank the rest of the payload.
     */
    const applyDelta = (delta: ServoThreadStateResponse): void => {
        if (!delta || typeof delta !== "object") return;
        // ``status.value`` is the reactive Proxy wrapping the
        // entity; calling ``patch`` through it ensures every
        // property write goes through Vue's ``set`` trap.
        status.value.patch(delta);
        mirrorToFacade();
    };

    const setConnectionStatus = (stat: string) => {
        connectionStatus.value = stat;
        mirrorToFacade();
    };

    return {status, connectionStatus, setFullState, applyDelta, setConnectionStatus};


});