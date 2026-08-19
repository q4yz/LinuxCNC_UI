// Machine-state entity. Wraps the wire shape produced by the
// backend's ``MachineState`` enum + ``MODE_*`` enums.
//
// ``state`` values mirror the backend's enum:
//   - "idle" | "loaded" | "running" | "paused" | "fault" |
//     "estop" | "off" | "updating"
//
// ``mode`` values mirror the backend:
//   - "manual" | "auto" | "mdi"

export const MACHINE_STATES = [
    "idle",
    "loaded",
    "running",
    "paused",
    "fault",
    "estop",
    "off",
    "updating",
] as const;

export type MachineStateType = typeof MACHINE_STATES[number];

export const MACHINE_MODES = ["manual", "auto", "mdi"] as const;

export type MachineModeType = typeof MACHINE_MODES[number];

export interface MachineStateParams {
    state?: string;
    mode?: string;
    isOnline?: boolean;
    isEstopped?: boolean;
    lastError?: string | null;
}

export class MachineState {
    private readonly _state: MachineStateType;
    private readonly _mode: MachineModeType;
    private readonly _isOnline: boolean;
    private readonly _isEstopped: boolean;
    private readonly _lastError: string | null;

    constructor({
                    state = "off",
                    mode = "manual",
                    isOnline = false,
                    isEstopped = false,
                    lastError = null,
                }: MachineStateParams = {}) {
        // We cast to any/type here because TS expects exactly the literal type in .includes()
        this._state = MACHINE_STATES.includes(state as MachineStateType)
            ? (state as MachineStateType)
            : "off";

        this._mode = MACHINE_MODES.includes(mode as MachineModeType)
            ? (mode as MachineModeType)
            : "manual";

        this._isOnline = Boolean(isOnline);
        this._isEstopped = Boolean(isEstopped);
        this._lastError = lastError;
    }

    get state(): MachineStateType {
        return this._state;
    }

    get mode(): MachineModeType {
        return this._mode;
    }

    get isOnline(): boolean {
        return this._isOnline;
    }

    get isEstopped(): boolean {
        return this._isEstopped;
    }

    get lastError(): string | null {
        return this._lastError;
    }

    get isRunning(): boolean {
        return this._state === "running";
    }

    get isLoaded(): boolean {
        return (
            this._state === "loaded" ||
            this._state === "running" ||
            this._state === "paused"
        );
    }

    get isPaused(): boolean {
        return this._state === "paused";
    }
}