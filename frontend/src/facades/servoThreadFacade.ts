// services/ServoThreadService.ts
import { useServoThreadStore } from '../stores/servoThread';
import { useConsoleStore } from '../stores/console';
import {ServoThreadState, WSEnvelope} from '../entities/servoThread/Telemetry'; // Adjust path if needed

const AXIS_NAMES: Record<number, string> = {
    0: 'X', 1: 'Y', 2: 'Z', 3: 'A', 4: 'B', 5: 'C', 6: 'U', 7: 'V', 8: 'W'
};

export class ServoThreadService {
    private ws: WebSocket | null = null;
    private reconnectTimer: number | null = null;

    // Track active keep-alive timers for continuous jogging
    private jogIntervals: Record<number, number> = {};

    connect() {
        const store = useServoThreadStore();
        const consoleStore = useConsoleStore();

        store.setConnectionStatus('connecting');
        this.ws = new WebSocket(`ws://${window.location.host}/ws/telemetry`);

        this.ws.onopen = () => {
            store.setConnectionStatus('connected');
            consoleStore.success('Telemetry connected');
        };

        this.ws.onmessage = (event) => {
            try {
                const envelope = WSEnvelope.fromTelemetryJSON(event.data);

                switch (envelope.type) {
                    case 'full_state':
                        // Routes through the store so the new
                        // ``ServoThreadState`` instance is wrapped by
                        // Vue's reactive ``Proxy`` and every
                        // dependent computed in ``stores/machine.ts``
                        // re-evaluates on the next tick.
                        store.setFullState(new ServoThreadState(envelope.data));
                        break;
                    case 'delta':
                        // Go through the store's own ``applyDelta``
                        // — calling ``store.status.patch(...)``
                        // directly bypasses Pinia's reactive surface
                        // for class-instance refs and silently drops
                        // the update. ``applyDelta`` calls
                        // ``status.value.patch(delta)`` which goes
                        // through the Vue ``set`` trap.
                        store.applyDelta(envelope.data);
                        break;
                    case 'error':
                        // The error envelope's ``data`` shape is not
                        // a ``ServoThreadStateResponse`` — the
                        // backend sends ``{kind, text, time}``. Treat
                        // it as ``unknown`` and pull ``.text`` only
                        // when present so a malformed frame cannot
                        // crash the WS loop.
                        if (
                            envelope.data &&
                            typeof envelope.data === "object" &&
                            "text" in envelope.data
                        ) {
                            const text = String(
                                (envelope.data as { text: unknown }).text,
                            );
                            consoleStore.error(text);
                        } else {
                            consoleStore.error("Unknown telemetry error payload");
                        }
                        break;
                    default:
                        console.warn('Unknown telemetry type:', envelope.type);
                }
            } catch (err) {
                console.error('Failed to parse telemetry message', err);
            }
        };

        this.ws.onclose = () => {
            store.setConnectionStatus('disconnected');
            consoleStore.warning('Telemetry disconnected');

            // Clear all active jog timers if the connection drops!
            this.clearAllJogIntervals();

            this.scheduleReconnect();
        };
    }

    send(payload: object) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(payload));
        } else {
            console.warn("Cannot send message, WebSocket is not open", payload);
        }
    }

    // --- Jogging Methods ---

    jogContinuous(axis: number, jogVelocity: number, intervalMs: number = 250) {
        const consoleStore = useConsoleStore();
        const axisName = AXIS_NAMES[axis] || `Axis ${axis}`;

        try {
            consoleStore.info(`Jogging ${axisName} axis continuously...`);

            // Start the jog over WS so the backend's watchdog registers it
            this.send({
                type: "jog_axis",
                velocities: { [axis]: jogVelocity },
                distance: 0,
            });

            // Clear any existing timer for this axis to prevent duplicates
            if (this.jogIntervals[axis]) {
                window.clearInterval(this.jogIntervals[axis]);
            }

            // Keep-alive cadence
            this.jogIntervals[axis] = window.setInterval(() => {
                this.send({ type: "jog_keepalive", axes: [axis] });
            }, intervalMs);

        } catch (err: any) {
            consoleStore.error(`Failed to start continuous jog: ${err.message}`);
            console.error("Failed to start continuous jog", err);
        }
    }

    jogStop(axis: number) {
        const consoleStore = useConsoleStore();
        const axisName = AXIS_NAMES[axis] || `Axis ${axis}`;

        try {
            // Clear the keep-alive interval first so a slow WS message
            // doesn't fire after the stop has been issued.
            if (this.jogIntervals[axis]) {
                window.clearInterval(this.jogIntervals[axis]);
                delete this.jogIntervals[axis];
            }

            // Prefer the WebSocket — the stop takes effect on the next tick
            this.send({ type: "jog_stop", axes: [axis] });
            consoleStore.info(`${axisName} Jog stopped`);

        } catch (err: any) {
            consoleStore.error(`Failed to stop jog: ${err.message}`);
            console.error("Failed to stop jog", err);
        }
    }

    private clearAllJogIntervals() {
        for (const axis in this.jogIntervals) {
            window.clearInterval(this.jogIntervals[axis]);
            delete this.jogIntervals[axis];
        }
    }

    private scheduleReconnect() {
        if (this.reconnectTimer) return;
        this.reconnectTimer = window.setTimeout(() => {
            this.reconnectTimer = null;
            this.connect();
        }, 2000);
    }

    disconnect() {
        if (this.reconnectTimer) window.clearTimeout(this.reconnectTimer);
        this.clearAllJogIntervals();
        if (this.ws) this.ws.close();
    }
}

export const servoThreadService = new ServoThreadService();