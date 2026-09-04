// services/ServoThreadService.ts
import { useServoThreadStore } from '../stores/servoThread';
import { useConsoleStore } from '../stores/console';
import { describeError } from '../core/error-format';
import {ServoThreadState, WSEnvelope} from '../entities/servoThread/Telemetry'; // Adjust path if needed
import {
    formatLinuxCNCError,
    isLinuxCNCError,
    type LinuxCNCErrorPayload,
} from '../core/linuxcnc-errors';

const AXIS_NAMES: Record<number, string> = {
    0: 'X', 1: 'Y', 2: 'Z', 3: 'A', 4: 'B', 5: 'C', 6: 'U', 7: 'V', 8: 'W'
};

/**
 * Track which error keys have already been replayed to the
 * console so a reconnect after a transient drop does not spam
 * the operator with every history row again. Keyed by
 * ``kind|text|time`` — the trio is stable across a single
 * backend session and the bounded history never grows past a
 * few hundred rows.
 */
const replayedErrorKeys = new Set<string>();

function errorKey(error: LinuxCNCErrorPayload): string {
    return `${error.kind ?? '?'}|${error.text ?? ''}|${error.time ?? ''}`;
}

function emitLinuxCNCError(
    consoleStore: ReturnType<typeof useConsoleStore>,
    payload: unknown,
    fallback: string,
): void {
    if (!isLinuxCNCError(payload)) {
        consoleStore.error(fallback);
        return;
    }
    const message = formatLinuxCNCError(payload);
    // ``popup: true`` so the toast layer fires — the operator
    // does not have to be looking at the console pane when an
    // ESTOP / soft-limit fires.
    consoleStore.error(message, { popup: true });
}

export class ServoThreadService {
    private ws: WebSocket | null = null;
    private reconnectTimer: number | null = null;

    // Set by ``disconnect()`` and cleared by ``connect()``. While
    // true, ``onclose`` must NOT schedule a reconnect — the app
    // shell closes the socket deliberately when the machine-online
    // heartbeat reports the backend down (see
    // ``composables/useMachineOnline.ts`` + ``App.vue``), and an
    // auto-reconnect loop against a dead port would recreate the
    // exact reconnect spam the gating is meant to eliminate.
    private manualClose = false;

    // Track active keep-alive timers for continuous jogging
    private jogIntervals: Record<number, number> = {};

    connect() {
        const store = useServoThreadStore();
        const consoleStore = useConsoleStore();

        this.manualClose = false;
        store.setConnectionStatus('connecting');
        this.ws = new WebSocket(`${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws/telemetry`);

        this.ws.onopen = () => {
            store.setConnectionStatus('connected');
            consoleStore.success('Telemetry connected');
            // Reset the replay ledger on every fresh socket —
            // the bounded history is about to land via
            // ``full_state`` and we want each row surfaced once.
            replayedErrorKeys.clear();
        };

        this.ws.onmessage = (event) => {
            // Stamp liveness FIRST — before any parsing. Every frame
            // (delta, full_state, error or the ~1 Hz backend
            // heartbeat) proves the transport is delivering; the
            // base-thread freeze watchdog reads this timestamp.
            store.noteWsMessage();

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
                        // Replay bounded error history through the
                        // console so the operator sees the backlog
                        // after a reload / reconnect — without this
                        // the operator would have to wait for a
                        // *new* error to surface anything at all.
                        this.replayErrorHistory(envelope.data);
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
                        // ``delta`` payloads only contain fields
                        // that changed, so a freshly-arrived
                        // ``errors`` array belongs here too. We
                        // still go through the replay ledger so we
                        // never double-log a row that landed in
                        // ``full_state``.
                        this.replayErrorHistory(envelope.data);
                        break;
                    case 'error':
                        // The error envelope's ``data`` shape is
                        // ``{kind, text, time}``. The store does
                        // not bother mirroring ``error`` envelopes
                        // into ``status.errors`` — the bounded
                        // history already arrived via ``full_state``
                        // — so we only have to fan out to the
                        // console.
                        emitLinuxCNCError(
                            consoleStore,
                            envelope.data,
                            "Unknown telemetry error payload",
                        );
                        break;
                    case 'heartbeat':
                        // Liveness-only frame (~1 Hz from the
                        // backend's telemetry loop). The timestamp
                        // was already stamped above; nothing to
                        // apply to state. Without this case every
                        // heartbeat would hit ``default`` and spam
                        // the console.
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

            // A deliberate close (machine went offline) must not
            // arm the reconnect loop — ``App.vue`` reconnects when
            // the machine-online heartbeat says the backend is back.
            if (this.manualClose) return;

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

        } catch (err: unknown) {
            consoleStore.error(`Failed to start continuous jog: ${describeError(err)}`);
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

        } catch (err: unknown) {
            consoleStore.error(`Failed to stop jog: ${describeError(err)}`);
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

    /**
     * Surface every error in ``payload.errors`` through the
     * console exactly once. Idempotent across reconnects: the
     * ``replayedErrorKeys`` ledger is cleared on every fresh
     * ``ws.onopen`` so the bounded history re-hydrates after
     * a reconnect without spamming duplicate rows for the
     * errors that were already replayed in the previous
     * session.
     */
    private replayErrorHistory(
        payload: { errors?: unknown } | null | undefined,
    ): void {
        if (!payload || !Array.isArray(payload.errors) || payload.errors.length === 0) {
            return;
        }
        const consoleStore = useConsoleStore();
        for (const raw of payload.errors) {
            if (!isLinuxCNCError(raw)) continue;
            const key = errorKey(raw);
            if (replayedErrorKeys.has(key)) continue;
            replayedErrorKeys.add(key);
            const message = formatLinuxCNCError(raw);
            // Replay uses ``popup: true`` so the operator sees
            // the backlog on reload without having to expand
            // the console panel manually.
            consoleStore.error(message, { popup: true });
        }
    }

    disconnect() {
        this.manualClose = true;
        if (this.reconnectTimer) window.clearTimeout(this.reconnectTimer);
        this.clearAllJogIntervals();
        if (this.ws) this.ws.close();
    }
}

export const servoThreadService = new ServoThreadService();