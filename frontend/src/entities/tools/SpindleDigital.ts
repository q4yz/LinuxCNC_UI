// Type-only import: generated model modules erase to empty modules
// under the runtime strip-types loader, so a value import would
// throw ``does not provide an export named ...`` in ``node --test``.
import type {SpindleDigitalCommand} from "../../../generated/api";


export type SpindleDirection = "forward" | "backward" | "stop";
export type SpindleDigitalAction = "forward" | "backward" | "stop" | "continue";

export class SpindleDigital {
    static readonly type = "digital_spindle" as const;
    readonly type = SpindleDigital.type;
    readonly id: string;
    readonly direction: SpindleDirection;
    /**
     * Live RPM reported by the HAL pin. ``null`` until the snapshot
     * has streamed at least one value — callers must NOT substitute
     * ``0`` and should treat ``null`` as "no data yet".
     */
    readonly actualRpm: number | null;
    readonly isConnected: boolean;
    readonly errorCount: number;
    readonly lastError: string;
    readonly atSpeed: boolean;
    readonly minRpm: number | null;
    readonly maxRpm: number | null;
    /**
     * Live ``absolute_master_override`` HAL pin value (RPM).
     * ``null`` until the first value has been streamed.
     */
    readonly masterOverride: number | null;
    /**
     * Live ``override`` HAL pin value as a fraction (0.0–4.0).
     * ``null`` until the first value has been streamed.
     */
    readonly override: number | null;
    readonly masterOverrideEnable: boolean | null;

    constructor(data: Partial<SpindleDigital> & { id: string }) {
        this.id = data.id;
        this.direction = data.direction ?? "stop";
        this.actualRpm = data.actualRpm ?? null;
        this.isConnected = data.isConnected ?? false;
        this.errorCount = data.errorCount ?? 0;
        this.lastError = data.lastError ?? "";
        this.atSpeed = data.atSpeed ?? false;
        this.minRpm = data.minRpm ?? null;
        this.maxRpm = data.maxRpm ?? null;
        this.masterOverride = data.masterOverride ?? null;
        this.override = data.override ?? null;
        this.masterOverrideEnable = data.masterOverrideEnable ?? null;
    }

    get isRunning(): boolean {
        return this.direction === "forward" || this.direction === "backward";
    }

    get fractionOfMax(): number {
        if (!this.maxRpm || this.maxRpm <= 0 || !this.actualRpm) return 0;
        return Math.max(0, Math.min(1, this.actualRpm / this.maxRpm));
    }
}

export class SpindleDigitalControlRequest {
    readonly toolId: string;
    readonly action: SpindleDigitalAction;
    readonly speed: number;
    readonly override: number;
    readonly masterOverride: number;
    readonly masterOverrideEnable: boolean;

    constructor(
        data: Partial<Omit<SpindleDigitalCommand, "toolId" | "action" | "speed">> & {
            toolId: string;
            action: SpindleDigitalAction;
            speed: number;
            // Accept both wire snake_case and entity camelCase names
            // for the override fields so legacy callers don't break.
            master_override?: number;
            masterOverride?: number;
            master_override_enable?: boolean;
            masterOverrideEnable?: boolean;
        }
    ) {
        this.toolId = data.toolId;
        this.action = data.action;
        this.speed = data.speed;
        this.override = data.override ?? 1.0;
        this.masterOverride = data.master_override ?? data.masterOverride ?? 0;
        this.masterOverrideEnable = data.master_override_enable ?? data.masterOverrideEnable ?? false;
    }
}